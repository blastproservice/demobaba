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
CREATE TABLE public.crm_auto_replies (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  keyword character varying NOT NULL,
  reply_text text NOT NULL,
  match_type character varying DEFAULT 'exact'::character varying,
  is_active boolean DEFAULT true,
  created_by bigint NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT crm_auto_replies_pkey PRIMARY KEY (id),
  CONSTRAINT crm_auto_replies_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id)
);
CREATE TABLE public.crm_blast_logs (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  campaign_id uuid NOT NULL,
  target_id character varying NOT NULL,
  status character varying NOT NULL,
  error_message text,
  sent_at timestamp with time zone DEFAULT now(),
  CONSTRAINT crm_blast_logs_pkey PRIMARY KEY (id),
  CONSTRAINT crm_blast_logs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.crm_campaigns(id)
);
CREATE TABLE public.crm_campaigns (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  campaign_name character varying NOT NULL,
  sender_type character varying NOT NULL,
  session_id bigint,
  message_template_id uuid NOT NULL,
  target_template_id uuid NOT NULL,
  status character varying DEFAULT 'PENDING'::character varying,
  scheduled_at timestamp with time zone,
  created_by bigint NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  frequency character varying DEFAULT 'ONCE'::character varying,
  interval_days integer DEFAULT 2,
  max_cycles integer DEFAULT 7,
  current_cycle integer DEFAULT 0,
  humanized_config jsonb DEFAULT '{}'::jsonb,
  total_target_cache integer DEFAULT 0,
  error_message text,
  CONSTRAINT crm_campaigns_pkey PRIMARY KEY (id),
  CONSTRAINT crm_campaigns_msg_tpl_fkey FOREIGN KEY (message_template_id) REFERENCES public.crm_templates(id),
  CONSTRAINT crm_campaigns_tgt_tpl_fkey FOREIGN KEY (target_template_id) REFERENCES public.crm_templates(id),
  CONSTRAINT crm_campaigns_session_fkey FOREIGN KEY (session_id) REFERENCES public.crm_telegram_sessions(id),
  CONSTRAINT crm_campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id)
);
CREATE TABLE public.crm_telegram_sessions (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  admin_id bigint NOT NULL,
  phone_number character varying NOT NULL UNIQUE,
  session_string text NOT NULL,
  ai_reply_active boolean DEFAULT false,
  status character varying DEFAULT 'active'::character varying,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT crm_telegram_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT crm_telegram_sessions_admin_id_fkey FOREIGN KEY (admin_id) REFERENCES public.admins(id)
);
CREATE TABLE public.crm_templates (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name character varying NOT NULL,
  type character varying NOT NULL,
  content text NOT NULL,
  created_by bigint NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT crm_templates_pkey PRIMARY KEY (id),
  CONSTRAINT crm_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.admins(id)
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
  source character varying DEFAULT 'bot'::character varying,
  last_interaction timestamp with time zone DEFAULT now(),
  loyalty_points integer DEFAULT 0,
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
CREATE TABLE public.loyalty_logs (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  customer_id uuid NOT NULL,
  transaction_type character varying NOT NULL,
  points integer NOT NULL,
  description text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT loyalty_logs_pkey PRIMARY KEY (id),
  CONSTRAINT loyalty_logs_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id)
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
  reference_type character varying DEFAULT 'ADJUSTMENT'::character varying,
  reference_id uuid,
  status character varying DEFAULT 'COMPLETED'::character varying,
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
CREATE TABLE public.store_rewards (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  name character varying NOT NULL,
  description text,
  cost_in_points integer NOT NULL,
  icon_name character varying DEFAULT 'gift'::character varying,
  is_active boolean DEFAULT true,
  stock_limit integer DEFAULT '-1'::integer,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT store_rewards_pkey PRIMARY KEY (id)
);
CREATE TABLE public.store_settings (
  id integer NOT NULL DEFAULT 1 CHECK (id = 1),
  store_name character varying DEFAULT 'BABA Parfume'::character varying,
  admin_whatsapp character varying,
  checkout_message text,
  is_bot_active boolean DEFAULT true,
  updated_at timestamp with time zone DEFAULT now(),
  ai_system_prompt text,
  store_email character varying,
  store_address text,
  maintenance_mode boolean DEFAULT false,
  CONSTRAINT store_settings_pkey PRIMARY KEY (id)
);
CREATE TABLE public.testimonials (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL,
  rating integer NOT NULL CHECK (rating >= 1 AND rating <= 5),
  review_text text,
  is_approved boolean DEFAULT false,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT testimonials_pkey PRIMARY KEY (id),
  CONSTRAINT testimonials_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id)
);