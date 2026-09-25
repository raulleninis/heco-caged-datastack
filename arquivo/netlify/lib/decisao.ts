// Regra de acesso, separada do gate para poder ser testada sem o runtime do Netlify.
//
// NEGAR POR PADRÃO: tudo exige login e o papel 'leitor', exceto esta lista
// explícita (comparação exata, nunca prefixo). O erro clássico é o inverso —
// proteger só um diretório e esquecer um caminho.

export const PUBLICO = ['/login.html', '/assets/login.js', '/robots.txt', '/favicon.ico']

// A API do Identity (login, recuperação de senha, convite) tem de ser alcançável
// SEM sessão, senão ninguém consegue criar uma: o login chama /.netlify/identity/token.
// É a única exceção por prefixo — e só desta API de autenticação do próprio Netlify.
export const PUBLICO_PREFIXOS = ['/.netlify/identity/']

export const PAPEL_LEITOR = 'leitor'

export type Decisao = 'liberar' | 'login' | 'proibido'

export interface UsuarioMinimo {
  roles?: string[]
}

export function decidir(pathname: string, user: UsuarioMinimo | null): Decisao {
  if (PUBLICO.includes(pathname) || PUBLICO_PREFIXOS.some((p) => pathname.startsWith(p))) return 'liberar'
  if (!user) return 'login'
  if (!user.roles?.includes(PAPEL_LEITOR)) return 'proibido'
  return 'liberar'
}
