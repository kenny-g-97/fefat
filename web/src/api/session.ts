import { useMutation } from "@tanstack/react-query"
import { apiTokensQuery } from "./api-tokens"
import { api, queryClient } from "./client"
import { answer, isRefusal, succeeded } from "./problems"
import type { components } from "./schema"

type PasswordChange = components["schemas"]["PasswordChange"]

/** Log in with the password, which sets the session's cookie. */
export function useLogin() {
  return useMutation({
    mutationFn: async (password: string) =>
      answer(await api.POST("/v1/auth/login", { body: { password } })),
  })
}

/** Log out; once the session has ended, or had already ended (401), the cache forgets what it
 * loaded. Any other refusal leaves the session, and the cache, as they are. */
export function useLogout() {
  return useMutation({
    mutationFn: async () => succeeded(await api.POST("/v1/auth/logout")),
    onSuccess: () => queryClient.clear(),
    onError: (error) => {
      if (isRefusal(error, 401)) {
        queryClient.clear()
      }
    },
  })
}

/** Change the password with the current one, which sets the cookie of a new session that keeps
 * this browser logged in and revokes every API token (step 5.2), so the token list is read
 * again. */
export function usePasswordChange() {
  return useMutation({
    mutationFn: async (change: PasswordChange) =>
      answer(await api.POST("/v1/auth/password", { body: change })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: apiTokensQuery.queryKey }),
  })
}
