import { useMutation } from "@tanstack/react-query"
import { api, identityQuery, queryClient } from "./client"
import { answer, succeeded } from "./problems"
import type { components } from "./schema"

type PasswordChange = components["schemas"]["PasswordChange"]

/** Log in with the password; the session's identity, with its CSRF token, goes to the
 * cache. */
export function useLogin() {
  return useMutation({
    mutationFn: async (password: string) =>
      answer(await api.POST("/v1/auth/login", { body: { password } })),
    onSuccess: (identity) =>
      queryClient.setQueryData(identityQuery.queryKey, identity),
  })
}

/** Log out; the cache forgets what the session loaded, whether or not the server
 * answered. */
export function useLogout() {
  return useMutation({
    mutationFn: async () => succeeded(await api.POST("/v1/auth/logout")),
    onSettled: () => queryClient.clear(),
  })
}

/** Change the password with the current one; the new session that keeps this browser
 * logged in, and its CSRF token, go to the cache. */
export function usePasswordChange() {
  return useMutation({
    mutationFn: async (change: PasswordChange) =>
      answer(await api.POST("/v1/auth/password", { body: change })),
    onSuccess: (identity) =>
      queryClient.setQueryData(identityQuery.queryKey, identity),
  })
}
