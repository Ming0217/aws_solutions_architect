/**
 * Clear Thinking — AI assist handler (Lambda response streaming).
 *
 * Invoked via a Lambda Function URL configured for RESPONSE_STREAM, so Bedrock
 * tokens are streamed straight to the browser (API Gateway can't stream). The
 * function URL auth type is NONE, so this handler verifies the caller's Cognito
 * access token itself (aws-jwt-verify) before doing any work — the endpoint is
 * internet-reachable but rejects anything without a valid token. That tradeoff
 * (self-auth on a public URL, hardened later with WAF) is documented in the
 * walkthrough.
 */
import {
  BedrockRuntimeClient,
  ConverseStreamCommand,
} from '@aws-sdk/client-bedrock-runtime';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, UpdateCommand } from '@aws-sdk/lib-dynamodb';
import { CognitoJwtVerifier } from 'aws-jwt-verify';
import { ASSIST_TYPES, buildPrompt, isAssistType, type DecisionInput } from './prompts';

// `awslambda` is a global injected by the Lambda runtime for response streaming.
declare const awslambda: {
  streamifyResponse: (
    handler: (event: FunctionUrlEvent, responseStream: NodeJS.WritableStream, context: unknown) => Promise<void>,
  ) => unknown;
  HttpResponseStream: {
    from: (
      stream: NodeJS.WritableStream,
      metadata: { statusCode: number; headers?: Record<string, string> },
    ) => NodeJS.WritableStream;
  };
};

interface FunctionUrlEvent {
  headers?: Record<string, string | undefined>;
  body?: string;
  isBase64Encoded?: boolean;
}

const MODEL_ID = process.env.MODEL_ID as string;
const TABLE_NAME = process.env.TABLE_NAME as string;
const DAILY_QUOTA = parseInt(process.env.DAILY_QUOTA ?? '25', 10);

const bedrock = new BedrockRuntimeClient({});
const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));

const verifier = CognitoJwtVerifier.create({
  userPoolId: process.env.USER_POOL_ID as string,
  tokenUse: 'access',
  clientId: process.env.CLIENT_ID as string,
});

/**
 * Atomically increment the caller's per-day assist counter and report whether
 * they're now over the cap. The counter item (pk=USER#<sub>, sk=QUOTA#<date>)
 * gets a 2-day TTL so it self-cleans. A cheap, hard ceiling on model spend.
 */
async function overDailyQuota(sub: string): Promise<boolean> {
  const day = new Date().toISOString().slice(0, 10); // UTC yyyy-mm-dd
  const ttl = Math.floor(Date.now() / 1000) + 2 * 24 * 3600;
  const res = await ddb.send(
    new UpdateCommand({
      TableName: TABLE_NAME,
      Key: { pk: `USER#${sub}`, sk: `QUOTA#${day}` },
      UpdateExpression: 'SET #ttl = if_not_exists(#ttl, :ttl) ADD #c :one',
      ExpressionAttributeNames: { '#ttl': 'ttl', '#c': 'count' },
      ExpressionAttributeValues: { ':ttl': ttl, ':one': 1 },
      ReturnValues: 'UPDATED_NEW',
    }),
  );
  return Number(res.Attributes?.count ?? 0) > DAILY_QUOTA;
}

function respond(
  stream: NodeJS.WritableStream,
  statusCode: number,
  headers: Record<string, string>,
): NodeJS.WritableStream {
  return awslambda.HttpResponseStream.from(stream, { statusCode, headers });
}

function fail(stream: NodeJS.WritableStream, statusCode: number, message: string): void {
  const s = respond(stream, statusCode, { 'content-type': 'application/json' });
  s.write(JSON.stringify({ message }));
  s.end();
}

export const handler = awslambda.streamifyResponse(
  async (event: FunctionUrlEvent, responseStream: NodeJS.WritableStream) => {
    // --- auth: verify the Cognito access token ---------------------------
    const authHeader = event.headers?.authorization ?? event.headers?.Authorization;
    const token = authHeader?.replace(/^Bearer\s+/i, '');
    if (!token) return fail(responseStream, 401, 'Missing bearer token');
    let sub: string;
    try {
      const claims = await verifier.verify(token);
      sub = String(claims.sub);
    } catch {
      return fail(responseStream, 401, 'Invalid token');
    }

    // --- parse + validate request ----------------------------------------
    let assist: unknown;
    let decision: DecisionInput;
    try {
      const raw = event.body
        ? event.isBase64Encoded
          ? Buffer.from(event.body, 'base64').toString('utf8')
          : event.body
        : '{}';
      const parsed = JSON.parse(raw) as { assist?: unknown; decision?: DecisionInput };
      assist = parsed.assist;
      decision = parsed.decision ?? {};
    } catch {
      return fail(responseStream, 400, 'Invalid JSON body');
    }
    if (!isAssistType(assist)) {
      return fail(responseStream, 400, `assist must be one of: ${ASSIST_TYPES.join(', ')}`);
    }

    // --- cost guardrail: per-user daily quota ----------------------------
    try {
      if (await overDailyQuota(sub)) {
        return fail(
          responseStream,
          429,
          `Daily AI limit reached (${DAILY_QUOTA} assists). Try again tomorrow.`,
        );
      }
    } catch (err) {
      console.error('quota check failed', err);
      // Fail closed on the quota check so a DynamoDB problem can't uncap spend.
      return fail(responseStream, 503, 'Service temporarily unavailable');
    }

    const { system, messages, maxTokens } = buildPrompt(assist, decision);

    // --- stream the model response ---------------------------------------
    const out = respond(responseStream, 200, {
      'content-type': 'text/plain; charset=utf-8',
    });

    try {
      const resp = await bedrock.send(
        new ConverseStreamCommand({
          modelId: MODEL_ID,
          system,
          messages,
          inferenceConfig: { maxTokens, temperature: 0.7 },
        }),
      );

      for await (const item of resp.stream ?? []) {
        const text = item.contentBlockDelta?.delta?.text;
        if (text) out.write(text);
      }
    } catch (err) {
      console.error('bedrock error', err);
      // Response has already started (200/streaming); surface a short marker.
      out.write('\n\n[the assist could not be completed — please try again]');
    } finally {
      out.end();
    }
  },
);
