-- Elecz Supabase Schema
-- Run this in Supabase SQL editor

-- Contracts table
create table contracts (
  id                      bigserial primary key,
  provider                text not null,
  zone                    text not null default 'FI',
  contract_type           text,         -- spot | fixed | fixed_term
  spot_margin_ckwh        float,
  basic_fee_eur_month     float,
  fixed_price_ckwh        float,
  contract_duration_months int,
  new_customers_only      boolean default false,
  below_wholesale         boolean default false,
  has_prepayment          boolean default false,
  data_errors             boolean default false,
  direct_url              text,
  affiliate_url           text,
  scraped_at              timestamptz,
  updated_at              timestamptz default now(),
  unique(provider, zone)
);

-- Clicks table (analytics + affiliate tracking)
create table clicks (
  id          bigserial primary key,
  provider    text not null,
  zone        text default 'FI',
  user_agent  text,
  referrer    text,
  clicked_at  timestamptz default now()
);

-- Index for analytics queries
create index idx_clicks_provider   on clicks(provider);
create index idx_clicks_clicked_at on clicks(clicked_at);
create index idx_contracts_zone    on contracts(zone);
