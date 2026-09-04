import Stripe from 'stripe'
const stripe = new Stripe('sk_live_FIXTURE_NOT_A_REAL_KEY_0000')
export async function POST(req: Request) {
  const event = await req.json()
  if (event.type === 'checkout.session.completed') { /* grant access */ }
  return new Response('ok', { headers: { 'Access-Control-Allow-Origin': '*' } })
}
