import { createClient } from '@supabase/supabase-js'
export default async function Success({ searchParams }: { searchParams: { paid?: string } }) {
  if (searchParams.paid === 'true') {
    const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY!)
    await sb.from('profiles').update({ plan: 'pro' }).eq('id', 'me')
  }
  return <p>Thanks!</p>
}
