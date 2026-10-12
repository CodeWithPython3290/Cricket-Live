-- Cricket League 3D: player accounts for online play.
-- Run this once in your Supabase project: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Safe to run again.

create table if not exists public.profiles (
  id         uuid primary key references auth.users (id) on delete cascade,
  username   text not null check (username ~ '^[A-Za-z0-9_]{3,16}$'),
  team       text not null default 'MI',
  wins       integer not null default 0,
  losses     integer not null default 0,
  created_at timestamptz not null default now()
);

-- Usernames are unique regardless of capitals (Ravi and ravi can't both exist).
create unique index if not exists profiles_username_lower on public.profiles (lower(username));

-- Row-level security: anyone can see profiles, but players can only create and edit their own.
alter table public.profiles enable row level security;

drop policy if exists "Profiles are visible to everyone" on public.profiles;
create policy "Profiles are visible to everyone"
  on public.profiles for select using (true);

drop policy if exists "Players create their own profile" on public.profiles;
create policy "Players create their own profile"
  on public.profiles for insert with check (auth.uid() = id);

drop policy if exists "Players update their own profile" on public.profiles;
create policy "Players update their own profile"
  on public.profiles for update using (auth.uid() = id) with check (auth.uid() = id);

-- Match rooms don't need a table: they use Supabase Realtime channels (broadcast + presence).
