import Stripe from 'stripe'
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)
export async function POST(req: Request) {
  const event = await req.json()
  if (event.type === 'checkout.session.completed') { /* grant access */ }
  return new Response('ok', { headers: { 'Access-Control-Allow-Origin': '*' } })
}
