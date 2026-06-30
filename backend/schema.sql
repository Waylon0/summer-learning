--
-- PostgreSQL database dump
--

\restrict QOCJxnLWBPxDvkQcaPBLsfB8VHEEfZGr76W3OP445Axus5hZLqg7QJGh4vsSgIz

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: approval_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_records (
    id character varying(36) NOT NULL,
    reimbursement_id character varying(36) NOT NULL,
    approver character varying(32) NOT NULL,
    step integer NOT NULL,
    action character varying(16) NOT NULL,
    comment text,
    acted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: department_budget; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.department_budget (
    id character varying(36) NOT NULL,
    department character varying(64) NOT NULL,
    annual_budget numeric(14,2) NOT NULL,
    used_amount numeric(14,2) NOT NULL,
    fiscal_year integer NOT NULL
);


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    id character varying(36) NOT NULL,
    reimbursement_id character varying(36) NOT NULL,
    invoice_code character varying(32),
    invoice_number character varying(32),
    amount numeric(12,2) NOT NULL,
    invoice_date date,
    seller_name character varying(128),
    buyer_name character varying(128),
    file_path character varying(256)
);


--
-- Name: reimbursements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reimbursements (
    id character varying(36) NOT NULL,
    user_id character varying(32) NOT NULL,
    user_name character varying(64) NOT NULL,
    department character varying(64) NOT NULL,
    expense_type character varying(32) NOT NULL,
    total_amount numeric(12,2) NOT NULL,
    description text,
    invoice_count integer NOT NULL,
    need_special_approval boolean NOT NULL,
    budget_remaining_after numeric(12,2),
    status character varying(16) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: approval_records approval_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_pkey PRIMARY KEY (id);


--
-- Name: department_budget department_budget_department_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.department_budget
    ADD CONSTRAINT department_budget_department_key UNIQUE (department);


--
-- Name: department_budget department_budget_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.department_budget
    ADD CONSTRAINT department_budget_pkey PRIMARY KEY (id);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: reimbursements reimbursements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reimbursements
    ADD CONSTRAINT reimbursements_pkey PRIMARY KEY (id);


--
-- Name: ix_approval_records_reimbursement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_records_reimbursement_id ON public.approval_records USING btree (reimbursement_id);


--
-- Name: ix_invoices_reimbursement_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoices_reimbursement_id ON public.invoices USING btree (reimbursement_id);


--
-- Name: ix_reimbursements_department; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reimbursements_department ON public.reimbursements USING btree (department);


--
-- Name: ix_reimbursements_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reimbursements_status ON public.reimbursements USING btree (status);


--
-- Name: ix_reimbursements_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reimbursements_user_id ON public.reimbursements USING btree (user_id);


--
-- Name: approval_records approval_records_reimbursement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_reimbursement_id_fkey FOREIGN KEY (reimbursement_id) REFERENCES public.reimbursements(id);


--
-- Name: invoices invoices_reimbursement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_reimbursement_id_fkey FOREIGN KEY (reimbursement_id) REFERENCES public.reimbursements(id);


--
-- PostgreSQL database dump complete
--

\unrestrict QOCJxnLWBPxDvkQcaPBLsfB8VHEEfZGr76W3OP445Axus5hZLqg7QJGh4vsSgIz

