// O bloqueio do arquivo. Intercepta TODA requisição (path '/*'), inclusive
// arquivos estáticos (PDF, XLSX) — o Identity sozinho protege só a aplicação.
// Que isto realmente vale para estáticos é o que scripts/verificar-bloqueio.sh prova.
import { getUser, refreshSession } from '@netlify/identity'
import type { Config, Context } from '@netlify/edge-functions'
import { decidir } from '../lib/decisao.ts'

const NEGADO = { 'Cache-Control': 'private, no-store' }

export default async (req: Request, context: Context) => {
  try {
    const { pathname } = new URL(req.url)

    // O JWT (nf_jwt) dura ~1 h. No servidor, getUser() valida o cookie como
    // está e devolve null se expirou; refreshSession() troca o refresh token
    // por um JWT novo antes disso, para a pessoa não ser deslogada de hora em hora.
    // Best effort: falhar aqui só significa "sem sessão" (nega), nunca "libera".
    let user = null
    const publica = decidir(pathname, null) === 'liberar'
    if (!publica) {
      await refreshSession().catch(() => null)
      user = await getUser()
    }

    switch (decidir(pathname, user)) {
      case 'liberar': {
        const resp = await context.next()
        resp.headers.set('Cache-Control', 'private, no-store')
        return resp
      }
      case 'login':
        return new Response(null, { status: 302, headers: { ...NEGADO, Location: '/login.html' } })
      default:
        return new Response('Forbidden', { status: 403, headers: NEGADO })
    }
  } catch {
    // Fail closed: qualquer erro inesperado nega, nunca deixa passar.
    return new Response('Service unavailable', { status: 503, headers: NEGADO })
  }
}

// Sem `onError`: o comportamento padrão de uma edge function que falha fora do
// try acima não foi confirmado na documentação — está na lista de verificação do README.
export const config: Config = { path: '/*' }
