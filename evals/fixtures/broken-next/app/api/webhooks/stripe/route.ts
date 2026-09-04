import Stripe from 'stripe'
const stripe = new Stripe('sk_live_51Hx9AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefgh')
export async function POST(req: Request) {
  const event = await req.json()
  if (event.type === 'checkout.session.completed') { /* grant access */ }
  return new Response('ok', { headers: { 'Access-Control-Allow-Origin': '*' } })
}
