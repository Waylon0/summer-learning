-- ============================================================================
-- ReimburseAgent — 数据库 Schema (PostgreSQL)
-- ============================================================================
-- 5 张核心表: reimbursements / invoices / department_budget / approval_records / expense_policy

CREATE TABLE IF NOT EXISTS reimbursements (
    id                      VARCHAR(36) PRIMARY KEY,
    user_id                 VARCHAR(32) NOT NULL,
    user_name               VARCHAR(64) NOT NULL,
    department              VARCHAR(64) NOT NULL,
    expense_type            VARCHAR(32) NOT NULL,
    total_amount            NUMERIC(12, 2) NOT NULL,
    description             TEXT,
    invoice_count           INTEGER NOT NULL DEFAULT 0,
    need_special_approval   BOOLEAN NOT NULL DEFAULT FALSE,
    budget_remaining_after  NUMERIC(12, 2),
    status                  VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reimbursements_user_id ON reimbursements (user_id);
CREATE INDEX IF NOT EXISTS ix_reimbursements_department ON reimbursements (department);
CREATE INDEX IF NOT EXISTS ix_reimbursements_status ON reimbursements (status);

CREATE TABLE IF NOT EXISTS invoices (
    id                 VARCHAR(36) PRIMARY KEY,
    reimbursement_id   VARCHAR(36) NOT NULL REFERENCES reimbursements(id),
    invoice_code       VARCHAR(32),
    invoice_number     VARCHAR(32),
    amount             NUMERIC(12, 2) NOT NULL,
    invoice_date       DATE,
    seller_name        VARCHAR(128),
    buyer_name         VARCHAR(128),
    file_path          VARCHAR(256)
);
CREATE INDEX IF NOT EXISTS ix_invoices_reimbursement_id ON invoices (reimbursement_id);

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
    approver           VARCHAR(32) NOT NULL,
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
