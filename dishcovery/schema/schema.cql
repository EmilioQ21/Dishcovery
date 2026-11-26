-- Dishcovery - Cassandra schema (one table per access pattern).
-- Applied by: python -m dishcovery.schema.init_all   (or: cqlsh -f dishcovery/schema/schema.cql)
-- Partition sizes are bounded: per-user and per-restaurant time series are bucketed by month
-- (or year for the passport), and the search history expires with a TTL.

CREATE KEYSPACE IF NOT EXISTS dishcovery
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- Q1  FR-22  a user's recent activity, newest first. Bucket = one month per partition.
CREATE TABLE IF NOT EXISTS dishcovery.activity_by_user (
  user_id     text,
  year_month  text,          -- '2026-11'
  event_ts    timestamp,
  event_id    timeuuid,
  event_type  text,          -- review | checkin | favorite | search | follow | list
  target_type text,          -- restaurant | dish | user | query | list
  target_id   text,
  details     map<text, text>,
  PRIMARY KEY ((user_id, year_month), event_ts, event_id)
) WITH CLUSTERING ORDER BY (event_ts DESC, event_id DESC);

-- Q2  FR-20, FR-21  food passport, newest visit first. Bucket = one year per partition.
CREATE TABLE IF NOT EXISTS dishcovery.visits_by_user (
  user_id         text,
  year            int,
  visited_at      timestamp,
  restaurant_id   text,
  restaurant_name text,      -- denormalized: the passport needs no second query
  cuisine         text,
  city            text,
  PRIMARY KEY ((user_id, year), visited_at, restaurant_id)
) WITH CLUSTERING ORDER BY (visited_at DESC, restaurant_id ASC);

-- Q3  FR-15, FR-17  a restaurant's reviews, newest first. Bucket = one month per partition.
CREATE TABLE IF NOT EXISTS dishcovery.reviews_by_restaurant (
  restaurant_id text,
  year_month    text,
  created_at    timestamp,
  review_id     text,
  user_id       text,
  user_name     text,
  dish_id       text,
  dish_name     text,
  rating        tinyint,
  text          text,
  PRIMARY KEY ((restaurant_id, year_month), created_at, review_id)
) WITH CLUSTERING ORDER BY (created_at DESC, review_id ASC);

-- Q4  FR-23  a user's last searches. Bounded by TTL: each search is kept 180 days.
CREATE TABLE IF NOT EXISTS dishcovery.searches_by_user (
  user_id     text,
  searched_at timestamp,
  search_id   timeuuid,
  query_text  text,
  filters     map<text, text>,
  PRIMARY KEY ((user_id), searched_at, search_id)
) WITH CLUSTERING ORDER BY (searched_at DESC, search_id DESC)
  AND default_time_to_live = 15552000;

-- Q5  FR-24  dish views per city per day (one partition per city-day, feeds weekly trending).
CREATE TABLE IF NOT EXISTS dishcovery.dish_views_by_day (
  city    text,
  day     date,
  dish_id text,
  views   counter,
  PRIMARY KEY ((city, day), dish_id)
);

-- Q6  FR-25  a user's visits in one month (stats: visits per month, most visited cuisine).
CREATE TABLE IF NOT EXISTS dishcovery.visits_by_user_month (
  user_id       text,
  year_month    text,
  visited_at    timestamp,
  restaurant_id text,
  cuisine       text,
  PRIMARY KEY ((user_id, year_month), visited_at, restaurant_id)
) WITH CLUSTERING ORDER BY (visited_at DESC, restaurant_id ASC);
