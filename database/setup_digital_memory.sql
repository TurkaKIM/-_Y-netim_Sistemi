-- Supabase Dashboard > SQL Editor alanında bir kez çalıştırın.
create extension if not exists pgcrypto;

create table if not exists public.ai_search_logs (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    query text not null check (char_length(query) <= 1000),
    response jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists ai_search_logs_created_at_idx
    on public.ai_search_logs (created_at desc);

create index if not exists ai_search_logs_user_id_idx
    on public.ai_search_logs (user_id, created_at desc);

alter table public.ai_search_logs enable row level security;

-- Tarayıcıdan doğrudan erişim kapalıdır. Kayıtlar yalnızca Streamlit sunucusundaki
-- service_role anahtarıyla yazılır; böylece anahtar istemciye gönderilmez.
revoke all on table public.ai_search_logs from anon, authenticated;
grant select, insert on table public.ai_search_logs to service_role;

notify pgrst, 'reload schema';
