-- ============================================================================
-- ReimburseAgent — 数据库 Schema (PostgreSQL)
-- ============================================================================
-- 8 张核心表: users / reimbursements / invoices / department_budget
--            / approval_records / expense_policy / conversations / conversation_messages

CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36) PRIMARY KEY,
    username        VARCHAR(64) NOT NULL UNIQUE,
    password_hash   VARCHAR(256) NOT NULL,
    name            VARCHAR(64) NOT NULL,
    email           VARCHAR(128),
    department      VARCHAR(64) NOT NULL,
    role            VARCHAR(16) NOT NULL DEFAULT 'employee',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_department ON users (department);

CREATE TABLE IF NOT EXISTS reimbursements (
    id                      VARCHAR(36) PRIMARY KEY,
    user_id                 VARCHAR(36) NOT NULL,
    user_name               VARCHAR(64) NOT NULL,
    department              VARCHAR(64) NOT NULL,
    expense_type            VARCHAR(32) NOT NULL,
    title                   VARCHAR(128),
    total_amount            NUMERIC(12, 2) NOT NULL DEFAULT 0,
    invoice_amount          NUMERIC(12, 2) DEFAULT 0,
    subsidy_amount          NUMERIC(12, 2) DEFAULT 0,
    description             TEXT,
    invoice_count           INTEGER NOT NULL DEFAULT 0,
    trip_destination        VARCHAR(64),
    trip_start_date         DATE,
    trip_end_date           DATE,
    trip_days               INTEGER,
    need_special_approval   BOOLEAN NOT NULL DEFAULT FALSE,
    budget_remaining_after  NUMERIC(12, 2),
    status                  VARCHAR(16) NOT NULL DEFAULT 'draft',
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reimbursements_user_id ON reimbursements (user_id);
CREATE INDEX IF NOT EXISTS ix_reimbursements_department ON reimbursements (department);
CREATE INDEX IF NOT EXISTS ix_reimbursements_status ON reimbursements (status);

-- 费用明细行（报销单 → 多条明细 → 每条明细多张发票）
CREATE TABLE IF NOT EXISTS expense_items (
    id                 VARCHAR(36) PRIMARY KEY,
    reimbursement_id   VARCHAR(36) NOT NULL REFERENCES reimbursements(id) ON DELETE CASCADE,
    seq                INTEGER NOT NULL DEFAULT 0,
    category           VARCHAR(32) NOT NULL,
    subtype            VARCHAR(32) NOT NULL,
    description        VARCHAR(256),
    unit_price         NUMERIC(12, 2),
    quantity           NUMERIC(10, 2) DEFAULT 1,
    unit               VARCHAR(16),
    amount             NUMERIC(12, 2) NOT NULL DEFAULT 0,
    evidence_type      VARCHAR(16) DEFAULT 'required',
    is_subsidy         BOOLEAN DEFAULT FALSE,
    needs_invoice      BOOLEAN DEFAULT TRUE,
    has_invoice        BOOLEAN DEFAULT FALSE,
    occur_date         DATE,
    from_location      VARCHAR(64),
    to_location        VARCHAR(64),
    created_at         TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_expense_items_reimbursement_id ON expense_items (reimbursement_id);

CREATE TABLE IF NOT EXISTS invoices (
    id                 VARCHAR(36) PRIMARY KEY,
    reimbursement_id   VARCHAR(36) NOT NULL REFERENCES reimbursements(id),
    expense_item_id    VARCHAR(36) REFERENCES expense_items(id),
    invoice_code       VARCHAR(32),
    invoice_number     VARCHAR(32),
    invoice_date       DATE,
    invoice_type       VARCHAR(32),
    seller_name        VARCHAR(128),
    seller_tax_id      VARCHAR(32),
    buyer_name         VARCHAR(128),
    buyer_tax_id       VARCHAR(32),
    amount             NUMERIC(12, 2) NOT NULL,
    tax_amount         NUMERIC(12, 2) DEFAULT 0,
    total_with_tax     NUMERIC(12, 2),
    file_path          VARCHAR(256)
);
CREATE INDEX IF NOT EXISTS ix_invoices_reimbursement_id ON invoices (reimbursement_id);
CREATE INDEX IF NOT EXISTS ix_invoices_expense_item_id ON invoices (expense_item_id);

CREATE TABLE IF NOT EXISTS department_budget (
    id              VARCHAR(36) PRIMARY KEY,
    department      VARCHAR(64) NOT NULL UNIQUE,
    annual_budget   NUMERIC(14, 2) NOT NULL,
    used_amount     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fiscal_year     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_records (
    id                 VARCHAR(36) PRIMARY KEY,
    reimbursement_id   VARCHAR(36) NOT NULL REFERENCES reimbursements(id),
    approver           VARCHAR(64) NOT NULL,
    step               INTEGER NOT NULL,
    action             VARCHAR(16) NOT NULL,
    comment            TEXT,
    acted_at           TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_approval_records_reimbursement_id ON approval_records (reimbursement_id);

CREATE TABLE IF NOT EXISTS expense_policy (
    id               VARCHAR(36) PRIMARY KEY,
    expense_type     VARCHAR(32) NOT NULL UNIQUE,
    max_per_trip     NUMERIC(12, 2),
    daily_limit      NUMERIC(12, 2),
    max_per_event    NUMERIC(12, 2),
    per_person_limit NUMERIC(12, 2),
    max_per_item     NUMERIC(12, 2),
    max_per_request  NUMERIC(12, 2),
    description      VARCHAR(128)
);

-- 会话管理（类 DeepSeek 网页多会话）
CREATE TABLE IF NOT EXISTS conversations (
    id           VARCHAR(36) PRIMARY KEY,
    user_id      VARCHAR(36) NOT NULL,
    title        VARCHAR(128) NOT NULL DEFAULT '新对话',
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id               VARCHAR(36) PRIMARY KEY,
    conversation_id  VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL DEFAULT 0,
    role             VARCHAR(16) NOT NULL,
    content          TEXT NOT NULL DEFAULT '',
    reasoning        TEXT,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_id ON conversation_messages (conversation_id);
