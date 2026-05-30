-- OAuth PKCE pending storage (replaces local oauth_pkce_pending.json).
-- Run in Supabase SQL Editor or via supabase db push.

create table if not exists public.oauth_pkce_pending (
    session_id text primary key,
    code_verifier text not null,
    code_challenge text not null default '',
    created_at timestamptz not null default now(),
    expires_at timestamptz not null
);

create index if not exists oauth_pkce_pending_expires_at_idx
    on public.oauth_pkce_pending (expires_at);

alter table public.oauth_pkce_pending enable row level security;

-- No direct table access for clients; use security-definer RPCs only.
revoke all on public.oauth_pkce_pending from anon, authenticated;

create or replace function public.store_oauth_pkce(
    p_session_id text,
    p_code_verifier text,
    p_code_challenge text default ''
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_session_id is null or length(p_session_id) < 16 then
        raise exception 'invalid session_id';
    end if;
    if p_code_verifier is null or length(p_code_verifier) < 43 then
        raise exception 'invalid code_verifier';
    end if;

    delete from public.oauth_pkce_pending where expires_at < now();

    insert into public.oauth_pkce_pending (session_id, code_verifier, code_challenge, expires_at)
    values (
        p_session_id,
        p_code_verifier,
        coalesce(p_code_challenge, ''),
        now() + interval '15 minutes'
    )
    on conflict (session_id) do update
        set code_verifier = excluded.code_verifier,
            code_challenge = excluded.code_challenge,
            expires_at = excluded.expires_at,
            created_at = now();
end;
$$;

create or replace function public.consume_oauth_pkce(p_session_id text)
returns table(code_verifier text, code_challenge text)
language plpgsql
security definer
set search_path = public
as $$
begin
    return query
        delete from public.oauth_pkce_pending o
        where o.session_id = p_session_id
          and o.expires_at > now()
        returning o.code_verifier, o.code_challenge;
end;
$$;

grant execute on function public.store_oauth_pkce(text, text, text) to anon, authenticated;
grant execute on function public.consume_oauth_pkce(text) to anon, authenticated;
