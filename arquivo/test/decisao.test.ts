import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decidir, PUBLICO } from '../netlify/lib/decisao.ts'

const leitor = { roles: ['leitor'] }

test('sem login: só a allow-list passa, o resto vai para o login', () => {
  for (const p of PUBLICO) assert.equal(decidir(p, null), 'liberar', p)
  for (const p of ['/', '/index.html', '/2026-06/boletim-202606.pdf', '/2026-06/planilha-202606.xlsx', '/_teste/teste.pdf', '/sitemap.xml']) {
    assert.equal(decidir(p, null), 'login', p)
  }
})

test('allow-list é comparação exata, não prefixo', () => {
  for (const p of ['/login.html/../index.html', '/login.html.bak', '/assets/login.js.map', '/assets/', '/robots.txt/x', '/LOGIN.HTML']) {
    assert.equal(decidir(p, null), 'login', p)
  }
})

test('a API do Identity é acessível sem login (senão o login nunca completa)', () => {
  for (const p of ['/.netlify/identity/settings', '/.netlify/identity/token', '/.netlify/identity/recover']) {
    assert.equal(decidir(p, null), 'liberar', p)
  }
})

test('a exceção do Identity não vaza para outros caminhos do Netlify nem para estáticos', () => {
  for (const p of ['/.netlify/functions/x', '/.netlify/identity', '/.netlify/identityx/token', '/.netlify/', '/identity/token', '/2026-06/.netlify/identity/x']) {
    assert.equal(decidir(p, null), 'login', p)
  }
  // dot-segments são resolvidos por new URL().pathname antes de chegar aqui
  assert.equal(decidir(new URL('https://s/.netlify/identity/../../index.html').pathname, null), 'login')
  assert.equal(decidir(new URL('https://s/.netlify/identity/%2e%2e/%2e%2e/2026-06/boletim.pdf').pathname, null), 'login')
})

test('cadastrado sem o papel leitor: 403', () => {
  assert.equal(decidir('/', { roles: [] }), 'proibido')
  assert.equal(decidir('/', {}), 'proibido')
  assert.equal(decidir('/', { roles: ['admin'] }), 'proibido')
})

test('leitor acessa tudo', () => {
  assert.equal(decidir('/', leitor), 'liberar')
  assert.equal(decidir('/2026-06/boletim-202606.pdf', leitor), 'liberar')
})
