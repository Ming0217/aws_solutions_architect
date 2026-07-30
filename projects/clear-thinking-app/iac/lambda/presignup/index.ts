/**
 * Clear Thinking — Cognito PreSignUp trigger (the invite gate).
 *
 * Self sign-up is enabled on the user pool, but this trigger runs before any
 * account is created and rejects any email that isn't on the allowlist — so the
 * pool is effectively invite-only while still letting invited people set their
 * own password (no admin-provisioned temp passwords). It fires for both native
 * sign-ups (PreSignUp_SignUp) and federated ones (PreSignUp_ExternalProvider,
 * e.g. Google), so the same allowlist gates every path.
 *
 * The allowlist is supplied via the ALLOWLIST env var (comma-separated emails)
 * so it can be edited without changing code.
 */

interface PreSignUpEvent {
  triggerSource: string;
  request: { userAttributes: Record<string, string> };
  response: {
    autoConfirmUser?: boolean;
    autoVerifyEmail?: boolean;
    autoVerifyPhone?: boolean;
  };
}

const allowlist = new Set(
  (process.env.ALLOWLIST ?? '')
    .split(',')
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean),
);

export const handler = async (event: PreSignUpEvent): Promise<PreSignUpEvent> => {
  const email = (event.request.userAttributes?.email ?? '').trim().toLowerCase();

  if (!email || !allowlist.has(email)) {
    // Throwing blocks the sign-up; the message is surfaced to the caller.
    throw new Error('This email is not on the invite list for Clear Thinking.');
  }

  // A federated (e.g. Google) account already has a provider-verified email —
  // trust it so the user isn't asked to re-verify.
  if (event.triggerSource === 'PreSignUp_ExternalProvider') {
    event.response.autoVerifyEmail = true;
  }

  return event;
};
