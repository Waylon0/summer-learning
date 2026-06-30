--
-- PostgreSQL database dump
--

\restrict pCkutFNLfhgpNlKl9n4uHZavdjFKw0zgcguz0YG9AMY2GhKUHehspVG38wpFmFi

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

--
-- Data for Name: department_budget; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.department_budget (id, department, annual_budget, used_amount, fiscal_year) FROM stdin;
aee8134a-3e76-42e7-8eff-e810db17f7f5	研发部	500000.00	120000.00	2026
e25bd4aa-860b-4044-99cf-68fd3ea7e39a	市场部	300000.00	85000.00	2026
9e3666d6-4fb7-42c6-9433-3eca516d0eaf	销售部	400000.00	220000.00	2026
9209f40f-a02a-424d-af0b-c44d49086dd6	人力资源部	150000.00	30000.00	2026
b30df38b-5b7e-4afd-9a9d-e7511a29812f	财务部	200000.00	45000.00	2026
acd924e3-04ce-4e37-a0e8-e6b1cbd67fbe	行政部	180000.00	60000.00	2026
411b9426-d0c9-4b08-8953-e931ca5d5afe	运维部	250000.00	90000.00	2026
\.


--
-- PostgreSQL database dump complete
--

\unrestrict pCkutFNLfhgpNlKl9n4uHZavdjFKw0zgcguz0YG9AMY2GhKUHehspVG38wpFmFi

