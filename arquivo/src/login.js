// Página de login. O Identity é headless (@netlify/identity): a interface é esta.
// Bundle gerado por `npm run build` em public/assets/login.js (não versionado).
import {
  acceptInvite,
  handleAuthCallback,
  login,
  logout,
  requestPasswordRecovery,
  updateUser,
} from '@netlify/identity'

const $ = (id) => document.getElementById(id)
const msg = (texto, ok = false) => {
  $('msg').textContent = texto
  $('msg').className = ok ? 'ok' : ''
}
const mostrar = (id) => {
  for (const f of ['f-login', 'f-senha']) $(f).hidden = f !== id
}
const entrar = () => location.replace('/')

// Mensagem genérica de propósito: não revela se o e-mail existe.
const ERRO_LOGIN = 'E-mail ou senha incorretos, ou acesso ainda não liberado.'

async function iniciar() {
  const params = new URLSearchParams(location.search)
  if (params.has('sair')) {
    await logout().catch(() => {})
    history.replaceState(null, '', '/login.html')
    return mostrar('f-login')
  }

  let retorno = null
  try {
    retorno = await handleAuthCallback()
  } catch {
    msg('Link inválido ou expirado. Peça um novo (use "Esqueci a senha").')
  }
  if (retorno) history.replaceState(null, '', '/login.html') // tira o token do endereço

  if (retorno?.type === 'invite' && retorno.token) {
    $('f-senha-txt').textContent = 'Bem-vindo. Defina a sua senha para ativar o acesso.'
    mostrar('f-senha')
    $('f-senha').onsubmit = async (e) => {
      e.preventDefault()
      try {
        await acceptInvite(retorno.token, $('nova').value)
        entrar()
      } catch {
        msg('Não foi possível definir a senha. O convite pode ter expirado.')
      }
    }
  } else if (retorno?.type === 'recovery') {
    $('f-senha-txt').textContent = 'Defina uma nova senha.'
    mostrar('f-senha')
    $('f-senha').onsubmit = async (e) => {
      e.preventDefault()
      try {
        await updateUser({ password: $('nova').value })
        entrar()
      } catch {
        msg('Não foi possível salvar a nova senha.')
      }
    }
  } else if (retorno?.type === 'confirmation' || retorno?.type === 'email_change') {
    entrar()
  } else {
    mostrar('f-login')
  }
}

$('f-login').onsubmit = async (e) => {
  e.preventDefault()
  try {
    await login($('email').value, $('senha').value)
    entrar()
  } catch {
    msg(ERRO_LOGIN)
  }
}

$('esqueci').onclick = async () => {
  const email = $('email').value
  if (!email) return msg('Digite o e-mail acima e clique de novo.')
  await requestPasswordRecovery(email).catch(() => {})
  msg('Se o e-mail tiver acesso, enviamos um link para redefinir a senha.', true)
}

iniciar()
