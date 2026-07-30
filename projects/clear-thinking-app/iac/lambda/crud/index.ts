/**
 * Clear Thinking — CRUD API handler.
 *
 * One Lambda behind an API Gateway HTTP API (payload format 2.0), fronted by a
 * Cognito user-pool JWT authorizer. Every route is scoped to the caller's own
 * data: the DynamoDB partition key is derived from the verified `sub` claim, so
 * a user can only ever read/write items under `USER#<their-sub>` — there is no
 * code path that lets a caller name another user's partition.
 *
 * Data model (single table):
 *   pk = USER#<sub>            sk = DECISION#<decisionId>
 * Deletion is a HARD delete (per the agreed "delete means gone" behaviour);
 * the item then ages out of the table's 35-day PITR window.
 */
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import {
  DynamoDBDocumentClient,
  PutCommand,
  GetCommand,
  DeleteCommand,
  QueryCommand,
} from '@aws-sdk/lib-dynamodb';
import { randomUUID } from 'node:crypto';

const TABLE_NAME = process.env.TABLE_NAME as string;
const MAX_BODY_BYTES = 200 * 1024; // reject oversized payloads early

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}), {
  marshallOptions: { removeUndefinedValues: true },
});

// --- minimal event/response shapes (avoids a dependency on @types/aws-lambda) --
interface ApiEvent {
  routeKey: string;
  rawPath: string;
  body?: string;
  isBase64Encoded?: boolean;
  pathParameters?: Record<string, string | undefined>;
  requestContext: {
    http: { method: string };
    authorizer?: { jwt?: { claims?: Record<string, unknown> } };
  };
}

interface ApiResult {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
}

const json = (statusCode: number, data?: unknown): ApiResult => ({
  statusCode,
  headers: { 'content-type': 'application/json' },
  body: data === undefined ? '' : JSON.stringify(data),
});

// Only these fields may be written by a client; everything else is server-owned.
//   title     — short label for the decision (derived from the problem statement)
//   fields    — the form's granular answers, an opaque { [fieldId]: string } map
//   completed — array of completed stage indices
//   status    — draft | decided
const EDITABLE_FIELDS = ['title', 'fields', 'completed', 'status'] as const;

const VALID_STATUS = new Set(['draft', 'decided']);

function pickEditable(input: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of EDITABLE_FIELDS) {
    if (input[key] !== undefined) out[key] = input[key];
  }
  return out;
}

function parseBody(event: ApiEvent): Record<string, unknown> {
  if (!event.body) return {};
  const raw = event.isBase64Encoded
    ? Buffer.from(event.body, 'base64').toString('utf8')
    : event.body;
  if (Buffer.byteLength(raw, 'utf8') > MAX_BODY_BYTES) {
    throw new HttpError(413, 'Payload too large');
  }
  const parsed = JSON.parse(raw);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new HttpError(400, 'Body must be a JSON object');
  }
  return parsed as Record<string, unknown>;
}

class HttpError extends Error {
  constructor(public statusCode: number, message: string) {
    super(message);
  }
}

function validate(input: Record<string, unknown>, requireTitle: boolean): void {
  if (requireTitle && (typeof input.title !== 'string' || input.title.trim() === '')) {
    throw new HttpError(400, 'title is required');
  }
  if (input.title !== undefined && typeof input.title !== 'string') {
    throw new HttpError(400, 'title must be a string');
  }
  if (
    input.fields !== undefined &&
    (typeof input.fields !== 'object' || input.fields === null || Array.isArray(input.fields))
  ) {
    throw new HttpError(400, 'fields must be an object');
  }
  if (input.completed !== undefined && !Array.isArray(input.completed)) {
    throw new HttpError(400, 'completed must be an array');
  }
  if (input.status !== undefined && !VALID_STATUS.has(String(input.status))) {
    throw new HttpError(400, 'status must be "draft" or "decided"');
  }
}

// strip internal keys before returning an item to the client
function toClient(item: Record<string, unknown>): Record<string, unknown> {
  const { pk, sk, ...rest } = item;
  return rest;
}

export const handler = async (event: ApiEvent): Promise<ApiResult> => {
  const sub = event.requestContext?.authorizer?.jwt?.claims?.sub;
  if (typeof sub !== 'string' || sub === '') {
    return json(401, { message: 'Unauthorized' });
  }
  const userPk = `USER#${sub}`;
  const id = event.pathParameters?.id;

  try {
    switch (event.routeKey) {
      case 'POST /decisions':
        return await createDecision(userPk, parseBody(event));
      case 'GET /decisions':
        return await listDecisions(userPk);
      case 'GET /decisions/{id}':
        return await getDecision(userPk, id);
      case 'PUT /decisions/{id}':
        return await updateDecision(userPk, id, parseBody(event));
      case 'DELETE /decisions/{id}':
        return await deleteDecision(userPk, id);
      default:
        return json(404, { message: `No route for ${event.routeKey}` });
    }
  } catch (err) {
    if (err instanceof HttpError) return json(err.statusCode, { message: err.message });
    if (err instanceof SyntaxError) return json(400, { message: 'Invalid JSON body' });
    console.error('unhandled error', err);
    return json(500, { message: 'Internal error' });
  }
};

async function createDecision(
  userPk: string,
  body: Record<string, unknown>,
): Promise<ApiResult> {
  const fields = pickEditable(body);
  validate(fields, true);

  const now = new Date().toISOString();
  const decisionId = randomUUID();
  const item = {
    pk: userPk,
    sk: `DECISION#${decisionId}`,
    decisionId,
    status: 'draft',
    ...fields,
    createdAt: now,
    updatedAt: now,
  };

  await ddb.send(new PutCommand({ TableName: TABLE_NAME, Item: item }));
  return json(201, toClient(item));
}

async function listDecisions(userPk: string): Promise<ApiResult> {
  const res = await ddb.send(
    new QueryCommand({
      TableName: TABLE_NAME,
      KeyConditionExpression: 'pk = :pk AND begins_with(sk, :prefix)',
      ExpressionAttributeValues: { ':pk': userPk, ':prefix': 'DECISION#' },
    }),
  );
  const items = (res.Items ?? []).map(toClient);
  return json(200, { items });
}

async function getDecision(userPk: string, id?: string): Promise<ApiResult> {
  if (!id) throw new HttpError(400, 'missing id');
  const res = await ddb.send(
    new GetCommand({ TableName: TABLE_NAME, Key: { pk: userPk, sk: `DECISION#${id}` } }),
  );
  if (!res.Item) return json(404, { message: 'Not found' });
  return json(200, toClient(res.Item));
}

async function updateDecision(
  userPk: string,
  id: string | undefined,
  body: Record<string, unknown>,
): Promise<ApiResult> {
  if (!id) throw new HttpError(400, 'missing id');
  const sk = `DECISION#${id}`;

  const existing = await ddb.send(
    new GetCommand({ TableName: TABLE_NAME, Key: { pk: userPk, sk } }),
  );
  if (!existing.Item) return json(404, { message: 'Not found' });

  const fields = pickEditable(body);
  validate(fields, false);

  const merged = {
    ...existing.Item,
    ...fields,
    pk: userPk,
    sk,
    updatedAt: new Date().toISOString(),
  };
  await ddb.send(new PutCommand({ TableName: TABLE_NAME, Item: merged }));
  return json(200, toClient(merged));
}

async function deleteDecision(userPk: string, id?: string): Promise<ApiResult> {
  if (!id) throw new HttpError(400, 'missing id');
  // Hard delete — "delete means gone". Item ages out of the PITR window naturally.
  await ddb.send(
    new DeleteCommand({ TableName: TABLE_NAME, Key: { pk: userPk, sk: `DECISION#${id}` } }),
  );
  return json(204);
}
