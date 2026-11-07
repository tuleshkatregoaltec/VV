/**
 * Hosted Supabase rejects /auth/v1 requests without an `apikey` header, while self-hosted GoTrue
 * ignores it. Send the publishable key only when one is configured.
 */
export function authClientHeaders(
	publishableKey: string | undefined
): Record<string, string> | undefined {
	const apikey = publishableKey?.trim()
	return apikey ? { apikey } : undefined
}
