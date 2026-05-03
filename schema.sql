-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.admins (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  username character varying NOT NULL UNIQUE,
  password_hash character varying NOT NULL,
  full_name character varying NOT NULL,
  role character varying NOT NULL DEFAULT 'visitor'::character varying,
  created_at timestamp with time zone DEFAULT now(),
  last_login timestamp with time zone,
  last_activity_desc text,
  CONSTRAINT admins_pkey PRIMARY KEY (id)
);
CREATE TABLE public.ai_chat_messages (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  session_id bigint NOT NULL,
  role character varying NOT NULL,
  content text NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT ai_chat_messages_pkey PRIMARY KEY (id),
  CONSTRAINT ai_chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.ai_chat_sessions(id)
);
CREATE TABLE public.ai_chat_sessions (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  telegram_id bigint NOT NULL,
  is_active boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT ai_chat_sessions_pkey PRIMARY KEY (id)
);
CREATE TABLE public.ai_feedbacks (
  id integer NOT NULL DEFAULT nextval('ai_feedbacks_id_seq'::regclass),
  telegram_id bigint NOT NULL,
  rating integer NOT NULL CHECK (rating >= 1 AND rating <= 5),
  complaint text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT ai_feedbacks_pkey PRIMARY KEY (id)
);
CREATE TABLE public.categories (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  name character varying NOT NULL,
  slug character varying NOT NULL UNIQUE,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT categories_pkey PRIMARY KEY (id)
);
CREATE TABLE public.customers (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  telegram_id bigint NOT NULL UNIQUE,
  username character varying,
  full_name character varying NOT NULL,
  phone character varying,
  default_address text,
  total_orders integer DEFAULT 0,
  total_spent numeric DEFAULT 0.00,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT customers_pkey PRIMARY KEY (id)
);
CREATE TABLE public.finance_accounts (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  bank_name character varying NOT NULL,
  account_number character varying,
  currency character varying DEFAULT 'IDR'::character varying,
  current_balance numeric DEFAULT 0.00,
  is_active boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT finance_accounts_pkey PRIMARY KEY (id)
);
CREATE TABLE public.finance_categories (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  category_name character varying NOT NULL,
  type character varying NOT NULL,
  description text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT finance_categories_pkey PRIMARY KEY (id)
);
CREATE TABLE public.finance_debts (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  debt_type character varying NOT NULL,
  person_name character varying NOT NULL,
  total_amount numeric NOT NULL,
  remaining_amount numeric NOT NULL,
  currency character varying DEFAULT 'IDR'::character varying,
  due_date date,
  status character varying DEFAULT 'BELUM LUNAS'::character varying,
  description text,
  created_by bigint,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT finance_debts_pkey PRIMARY KEY (id),
  CONSTRAINT finance_debts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id)
);
CREATE TABLE public.finance_mutations (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  account_id bigint NOT NULL,
  category_id bigint NOT NULL,
  transaction_type character varying NOT NULL,
  amount numeric NOT NULL,
  balance_after numeric NOT NULL,
  description text,
  reference_order_id uuid,
  reference_purchase_id uuid,
  created_by bigint,
  created_at timestamp with time zone DEFAULT now(),
  reference_debt_id uuid,
  CONSTRAINT finance_mutations_pkey PRIMARY KEY (id),
  CONSTRAINT finance_mutations_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.finance_accounts(id),
  CONSTRAINT finance_mutations_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.finance_categories(id),
  CONSTRAINT finance_mutations_order_id_fkey FOREIGN KEY (reference_order_id) REFERENCES public.orders(id),
  CONSTRAINT finance_mutations_purchase_id_fkey FOREIGN KEY (reference_purchase_id) REFERENCES public.stock_purchases(id),
  CONSTRAINT finance_mutations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id),
  CONSTRAINT finance_mutations_reference_debt_id_fkey FOREIGN KEY (reference_debt_id) REFERENCES public.finance_debts(id)
);
CREATE TABLE public.order_items (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  order_id uuid,
  product_id bigint,
  quantity integer NOT NULL,
  price_at_time numeric NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT order_items_pkey PRIMARY KEY (id),
  CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id),
  CONSTRAINT order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id)
);
CREATE TABLE public.orders (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  order_number character varying NOT NULL UNIQUE,
  customer_id uuid,
  shipping_address text,
  total_amount numeric NOT NULL,
  status character varying DEFAULT 'Menunggu Pembayaran'::character varying,
  order_source character varying DEFAULT 'Telegram Bot'::character varying,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  payment_method character varying DEFAULT 'COD'::character varying,
  CONSTRAINT orders_pkey PRIMARY KEY (id),
  CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id)
);
CREATE TABLE public.products (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  name character varying NOT NULL,
  category_id bigint,
  tags ARRAY DEFAULT '{}'::text[],
  tagline character varying,
  description text,
  top_notes ARRAY DEFAULT '{}'::text[],
  heart_notes ARRAY DEFAULT '{}'::text[],
  base_notes ARRAY DEFAULT '{}'::text[],
  longevity character varying,
  recommendation character varying,
  image_url text,
  original_price numeric NOT NULL,
  discounted_price numeric NOT NULL,
  stock_quantity integer DEFAULT 0,
  is_active boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT products_pkey PRIMARY KEY (id),
  CONSTRAINT products_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.categories(id)
);
CREATE TABLE public.stock_logs (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  product_id bigint NOT NULL,
  action character varying NOT NULL,
  adjustment_amount integer NOT NULL,
  final_stock integer NOT NULL,
  reason text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT stock_logs_pkey PRIMARY KEY (id),
  CONSTRAINT stock_logs_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id)
);
CREATE TABLE public.stock_purchase_items (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  purchase_id uuid NOT NULL,
  product_id bigint,
  item_name character varying NOT NULL,
  quantity integer NOT NULL,
  capital_price_per_unit numeric NOT NULL,
  subtotal numeric NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT stock_purchase_items_pkey PRIMARY KEY (id),
  CONSTRAINT stock_purchase_items_purchase_id_fkey FOREIGN KEY (purchase_id) REFERENCES public.stock_purchases(id),
  CONSTRAINT stock_purchase_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id)
);
CREATE TABLE public.stock_purchases (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  purchase_number character varying NOT NULL UNIQUE,
  account_id bigint,
  total_items_cost numeric NOT NULL DEFAULT 0.00,
  shipping_cost numeric DEFAULT 0.00,
  grand_total numeric NOT NULL DEFAULT 0.00,
  notes text,
  created_by bigint,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT stock_purchases_pkey PRIMARY KEY (id),
  CONSTRAINT stock_purchases_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.finance_accounts(id),
  CONSTRAINT stock_purchases_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id)
);
CREATE TABLE public.store_settings (
  id integer NOT NULL DEFAULT 1 CHECK (id = 1),
  store_name character varying DEFAULT 'BABA Parfume'::character varying,
  admin_whatsapp character varying,
  checkout_message text,
  is_bot_active boolean DEFAULT true,
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT store_settings_pkey PRIMARY KEY (id)
);