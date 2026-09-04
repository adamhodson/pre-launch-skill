create table profiles (id uuid primary key, email text, plan text);
create table documents (id uuid primary key, owner uuid references profiles(id), body text);
alter table documents disable row level security;
