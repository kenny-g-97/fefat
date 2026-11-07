import { z } from "zod"

// zod's compiler probes `new Function` when a schema is built, which the server's content
// security policy refuses and the browser reports as a violation even though zod catches it
// (01-architecture.md section 8). main.tsx imports this module first, before any schema.
z.config({ jitless: true })
