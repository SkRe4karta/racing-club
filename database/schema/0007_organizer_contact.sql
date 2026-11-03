--
-- PostgreSQL database dump
--

\restrict LAB8SCHEMA


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: racing_audit_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.racing_audit_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN RAISE EXCEPTION 'audit history is append-only'; END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: application_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.application_events (
    id integer NOT NULL,
    application_id integer NOT NULL,
    actor_id integer NOT NULL,
    action character varying(24) NOT NULL,
    status character varying(24) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_application_events_action CHECK (((action)::text = ANY ((ARRAY['created'::character varying, 'confirmed'::character varying, 'rejected'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT ck_application_events_status CHECK (((status)::text = ANY ((ARRAY['awaiting_owner'::character varying, 'awaiting_jockey'::character varying, 'pending_admin'::character varying, 'admin_confirmed'::character varying, 'rejected'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: application_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.application_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: application_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.application_events_id_seq OWNED BY public.application_events.id;


--
-- Name: applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.applications (
    id integer NOT NULL,
    competition_id integer NOT NULL,
    horse_id integer NOT NULL,
    jockey_id integer NOT NULL,
    owner_user_id integer NOT NULL,
    jockey_user_id integer NOT NULL,
    initiator_id integer NOT NULL,
    initiator_side character varying(16) NOT NULL,
    status character varying(24) NOT NULL,
    owner_confirmed_at timestamp with time zone,
    jockey_confirmed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_applications_consents CHECK (((((status)::text = 'awaiting_owner'::text) AND (owner_confirmed_at IS NULL) AND (jockey_confirmed_at IS NOT NULL) AND ((initiator_side)::text = 'jockey'::text)) OR (((status)::text = 'awaiting_jockey'::text) AND (owner_confirmed_at IS NOT NULL) AND (jockey_confirmed_at IS NULL) AND ((initiator_side)::text = 'owner'::text)) OR (((status)::text = ANY ((ARRAY['pending_admin'::character varying, 'admin_confirmed'::character varying])::text[])) AND (owner_confirmed_at IS NOT NULL) AND (jockey_confirmed_at IS NOT NULL)) OR ((status)::text = ANY ((ARRAY['rejected'::character varying, 'cancelled'::character varying])::text[])))),
    CONSTRAINT ck_applications_distinct_parties CHECK ((owner_user_id <> jockey_user_id)),
    CONSTRAINT ck_applications_side CHECK (((initiator_side)::text = ANY ((ARRAY['owner'::character varying, 'jockey'::character varying])::text[]))),
    CONSTRAINT ck_applications_status CHECK (((status)::text = ANY ((ARRAY['awaiting_owner'::character varying, 'awaiting_jockey'::character varying, 'pending_admin'::character varying, 'admin_confirmed'::character varying, 'rejected'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: applications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.applications_id_seq OWNED BY public.applications.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    actor_id integer NOT NULL,
    action character varying(48) NOT NULL,
    object_type character varying(32) NOT NULL,
    object_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    reason character varying(500),
    old_values json,
    new_values json
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: auth_throttles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_throttles (
    key character varying(64) NOT NULL,
    window_started bigint NOT NULL,
    attempts integer NOT NULL,
    CONSTRAINT ck_auth_throttles_attempts CHECK ((attempts > 0))
);


--
-- Name: competitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competitions (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    event_date date NOT NULL,
    event_time time without time zone NOT NULL,
    location character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    registration_deadline timestamp with time zone,
    distance integer,
    max_participants integer,
    revision integer DEFAULT 0 NOT NULL,
    registration_notes character varying(2000),
    organizer_email character varying(254),
    CONSTRAINT ck_competitions_capacity CHECK (((max_participants IS NULL) OR ((max_participants >= 1) AND (max_participants <= 1000)))),
    CONSTRAINT ck_competitions_distance CHECK (((distance IS NULL) OR ((distance >= 100) AND (distance <= 100000)))),
    CONSTRAINT ck_competitions_organizer_email CHECK (((organizer_email IS NULL) OR (((length((organizer_email)::text) >= 3) AND (length((organizer_email)::text) <= 254)) AND ((organizer_email)::text = lower((organizer_email)::text)) AND ((organizer_email)::text ~~ '%@%'::text)))),
    CONSTRAINT ck_competitions_registration_notes CHECK (((registration_notes IS NULL) OR (length((registration_notes)::text) <= 2000)))
);


--
-- Name: competitions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.competitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: competitions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.competitions_id_seq OWNED BY public.competitions.id;


--
-- Name: horses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.horses (
    id integer NOT NULL,
    nickname character varying(100) NOT NULL,
    gender character varying(20) NOT NULL,
    age integer NOT NULL,
    owner_id integer NOT NULL
);


--
-- Name: horses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.horses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: horses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.horses_id_seq OWNED BY public.horses.id;


--
-- Name: jockeys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jockeys (
    id integer NOT NULL,
    full_name character varying(150) NOT NULL,
    address character varying(255),
    age integer NOT NULL,
    rating double precision NOT NULL
);


--
-- Name: jockeys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.jockeys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: jockeys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.jockeys_id_seq OWNED BY public.jockeys.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    user_id integer NOT NULL,
    application_id integer,
    event_id integer,
    message character varying(300) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    read_at timestamp with time zone,
    audit_id integer,
    competition_id integer,
    CONSTRAINT ck_notifications_source CHECK ((((event_id IS NOT NULL) AND (application_id IS NOT NULL) AND (audit_id IS NULL)) OR ((event_id IS NULL) AND (audit_id IS NOT NULL))))
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: owners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owners (
    id integer NOT NULL,
    full_name character varying(150) NOT NULL,
    address character varying(255),
    phone character varying(50)
);


--
-- Name: owners_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.owners_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: owners_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.owners_id_seq OWNED BY public.owners.id;


--
-- Name: prediction_choices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prediction_choices (
    id integer NOT NULL,
    prediction_id integer NOT NULL,
    horse_id integer NOT NULL,
    "position" integer NOT NULL,
    position_correct boolean,
    CONSTRAINT ck_prediction_choices_position CHECK ((("position" >= 1) AND ("position" <= 3)))
);


--
-- Name: prediction_choices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prediction_choices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prediction_choices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prediction_choices_id_seq OWNED BY public.prediction_choices.id;


--
-- Name: predictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.predictions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    competition_id integer NOT NULL,
    mode character varying(12) NOT NULL,
    revision integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    evaluated_at timestamp with time zone,
    protocol_revision integer,
    outcome character varying(12) NOT NULL,
    winner_correct boolean,
    podium_hits integer,
    exact_trio boolean,
    CONSTRAINT ck_predictions_hits CHECK (((podium_hits IS NULL) OR ((podium_hits >= 0) AND (podium_hits <= 3)))),
    CONSTRAINT ck_predictions_mode CHECK (((mode)::text = ANY ((ARRAY['winner'::character varying, 'trio'::character varying])::text[]))),
    CONSTRAINT ck_predictions_outcome CHECK (((outcome)::text = ANY ((ARRAY['pending'::character varying, 'evaluated'::character varying, 'void'::character varying])::text[]))),
    CONSTRAINT ck_predictions_revision CHECK ((revision > 0))
);


--
-- Name: predictions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.predictions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: predictions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.predictions_id_seq OWNED BY public.predictions.id;


--
-- Name: results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.results (
    id integer NOT NULL,
    competition_id integer NOT NULL,
    horse_id integer NOT NULL,
    jockey_id integer NOT NULL,
    finish_time_seconds double precision,
    is_disqualified boolean NOT NULL,
    place integer,
    application_id integer,
    start_number integer,
    did_not_finish boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_results_outcome CHECK ((NOT (did_not_finish AND is_disqualified))),
    CONSTRAINT ck_results_start_number CHECK (((start_number IS NULL) OR (start_number > 0)))
);


--
-- Name: results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.results_id_seq OWNED BY public.results.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(254) NOT NULL,
    password_hash character varying(512) NOT NULL,
    role character varying(16) NOT NULL,
    status character varying(16) NOT NULL,
    registered_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone,
    owner_id integer,
    jockey_id integer,
    CONSTRAINT ck_users_email_normalized CHECK (((email)::text = lower((email)::text))),
    CONSTRAINT ck_users_profile_role CHECK (((((role)::text = 'OWNER'::text) AND (owner_id IS NOT NULL) AND (jockey_id IS NULL)) OR (((role)::text = 'JOCKEY'::text) AND (jockey_id IS NOT NULL) AND (owner_id IS NULL)) OR (((role)::text = ANY ((ARRAY['ROOT'::character varying, 'ADMIN'::character varying, 'VIEWER'::character varying])::text[])) AND (owner_id IS NULL) AND (jockey_id IS NULL)))),
    CONSTRAINT ck_users_role CHECK (((role)::text = ANY ((ARRAY['ROOT'::character varying, 'ADMIN'::character varying, 'OWNER'::character varying, 'JOCKEY'::character varying, 'VIEWER'::character varying])::text[]))),
    CONSTRAINT ck_users_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: application_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_events ALTER COLUMN id SET DEFAULT nextval('public.application_events_id_seq'::regclass);


--
-- Name: applications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications ALTER COLUMN id SET DEFAULT nextval('public.applications_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: competitions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitions ALTER COLUMN id SET DEFAULT nextval('public.competitions_id_seq'::regclass);


--
-- Name: horses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.horses ALTER COLUMN id SET DEFAULT nextval('public.horses_id_seq'::regclass);


--
-- Name: jockeys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jockeys ALTER COLUMN id SET DEFAULT nextval('public.jockeys_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: owners id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owners ALTER COLUMN id SET DEFAULT nextval('public.owners_id_seq'::regclass);


--
-- Name: prediction_choices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices ALTER COLUMN id SET DEFAULT nextval('public.prediction_choices_id_seq'::regclass);


--
-- Name: predictions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.predictions ALTER COLUMN id SET DEFAULT nextval('public.predictions_id_seq'::regclass);


--
-- Name: results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results ALTER COLUMN id SET DEFAULT nextval('public.results_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: application_events application_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_events
    ADD CONSTRAINT application_events_pkey PRIMARY KEY (id);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: auth_throttles auth_throttles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_throttles
    ADD CONSTRAINT auth_throttles_pkey PRIMARY KEY (key);


--
-- Name: competitions competitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitions
    ADD CONSTRAINT competitions_pkey PRIMARY KEY (id);


--
-- Name: horses horses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.horses
    ADD CONSTRAINT horses_pkey PRIMARY KEY (id);


--
-- Name: jockeys jockeys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jockeys
    ADD CONSTRAINT jockeys_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: owners owners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owners
    ADD CONSTRAINT owners_pkey PRIMARY KEY (id);


--
-- Name: prediction_choices prediction_choices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices
    ADD CONSTRAINT prediction_choices_pkey PRIMARY KEY (id);


--
-- Name: predictions predictions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (id);


--
-- Name: results results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT results_pkey PRIMARY KEY (id);


--
-- Name: results uq_competition_horse; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT uq_competition_horse UNIQUE (competition_id, horse_id);


--
-- Name: results uq_competition_jockey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT uq_competition_jockey UNIQUE (competition_id, jockey_id);


--
-- Name: notifications uq_notifications_recipient_audit; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT uq_notifications_recipient_audit UNIQUE (user_id, audit_id);


--
-- Name: notifications uq_notifications_recipient_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT uq_notifications_recipient_event UNIQUE (user_id, event_id);


--
-- Name: prediction_choices uq_prediction_choices_horse; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices
    ADD CONSTRAINT uq_prediction_choices_horse UNIQUE (prediction_id, horse_id);


--
-- Name: prediction_choices uq_prediction_choices_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices
    ADD CONSTRAINT uq_prediction_choices_position UNIQUE (prediction_id, "position");


--
-- Name: predictions uq_predictions_user_race_mode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT uq_predictions_user_race_mode UNIQUE (user_id, competition_id, mode);


--
-- Name: results uq_results_application; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT uq_results_application UNIQUE (application_id);


--
-- Name: results uq_results_start_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT uq_results_start_number UNIQUE (competition_id, start_number);


--
-- Name: users users_jockey_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_jockey_id_key UNIQUE (jockey_id);


--
-- Name: users users_owner_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_owner_id_key UNIQUE (owner_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_application_events_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_application_events_application_id ON public.application_events USING btree (application_id);


--
-- Name: ix_applications_jockey_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_applications_jockey_created ON public.applications USING btree (jockey_user_id, created_at);


--
-- Name: ix_applications_owner_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_applications_owner_created ON public.applications USING btree (owner_user_id, created_at);


--
-- Name: ix_audit_logs_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_actor_id ON public.audit_logs USING btree (actor_id);


--
-- Name: ix_audit_logs_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_object ON public.audit_logs USING btree (object_type, object_id, id);


--
-- Name: ix_notifications_user_read; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_read ON public.notifications USING btree (user_id, read_at, id);


--
-- Name: ix_predictions_competition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_predictions_competition ON public.predictions USING btree (competition_id);


--
-- Name: ix_predictions_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_predictions_user_created ON public.predictions USING btree (user_id, created_at);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: uq_applications_active_horse; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_applications_active_horse ON public.applications USING btree (competition_id, horse_id) WHERE ((status)::text = ANY ((ARRAY['awaiting_owner'::character varying, 'awaiting_jockey'::character varying, 'pending_admin'::character varying, 'admin_confirmed'::character varying])::text[]));


--
-- Name: uq_applications_active_jockey; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_applications_active_jockey ON public.applications USING btree (competition_id, jockey_id) WHERE ((status)::text = ANY ((ARRAY['awaiting_owner'::character varying, 'awaiting_jockey'::character varying, 'pending_admin'::character varying, 'admin_confirmed'::character varying])::text[]));


--
-- Name: uq_users_initial_root; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_users_initial_root ON public.users USING btree (role) WHERE ((role)::text = 'ROOT'::text);


--
-- Name: audit_logs audit_logs_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_logs_immutable BEFORE DELETE OR UPDATE ON public.audit_logs FOR EACH ROW EXECUTE FUNCTION public.racing_audit_immutable();


--
-- Name: application_events application_events_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_events
    ADD CONSTRAINT application_events_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: application_events application_events_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_events
    ADD CONSTRAINT application_events_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE RESTRICT;


--
-- Name: applications applications_competition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_competition_id_fkey FOREIGN KEY (competition_id) REFERENCES public.competitions(id) ON DELETE RESTRICT;


--
-- Name: applications applications_horse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_horse_id_fkey FOREIGN KEY (horse_id) REFERENCES public.horses(id) ON DELETE RESTRICT;


--
-- Name: applications applications_initiator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_initiator_id_fkey FOREIGN KEY (initiator_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: applications applications_jockey_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_jockey_id_fkey FOREIGN KEY (jockey_id) REFERENCES public.jockeys(id) ON DELETE RESTRICT;


--
-- Name: applications applications_jockey_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_jockey_user_id_fkey FOREIGN KEY (jockey_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: applications applications_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: audit_logs audit_logs_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: notifications fk_notifications_audit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_audit FOREIGN KEY (audit_id) REFERENCES public.audit_logs(id) ON DELETE RESTRICT;


--
-- Name: notifications fk_notifications_competition; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_competition FOREIGN KEY (competition_id) REFERENCES public.competitions(id) ON DELETE RESTRICT;


--
-- Name: results fk_results_application; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT fk_results_application FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE RESTRICT;


--
-- Name: horses horses_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.horses
    ADD CONSTRAINT horses_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.owners(id);


--
-- Name: notifications notifications_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE RESTRICT;


--
-- Name: notifications notifications_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.application_events(id) ON DELETE RESTRICT;


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: prediction_choices prediction_choices_horse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices
    ADD CONSTRAINT prediction_choices_horse_id_fkey FOREIGN KEY (horse_id) REFERENCES public.horses(id) ON DELETE RESTRICT;


--
-- Name: prediction_choices prediction_choices_prediction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prediction_choices
    ADD CONSTRAINT prediction_choices_prediction_id_fkey FOREIGN KEY (prediction_id) REFERENCES public.predictions(id) ON DELETE RESTRICT;


--
-- Name: predictions predictions_competition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_competition_id_fkey FOREIGN KEY (competition_id) REFERENCES public.competitions(id) ON DELETE RESTRICT;


--
-- Name: predictions predictions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: results results_competition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT results_competition_id_fkey FOREIGN KEY (competition_id) REFERENCES public.competitions(id);


--
-- Name: results results_horse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT results_horse_id_fkey FOREIGN KEY (horse_id) REFERENCES public.horses(id);


--
-- Name: results results_jockey_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.results
    ADD CONSTRAINT results_jockey_id_fkey FOREIGN KEY (jockey_id) REFERENCES public.jockeys(id);


--
-- Name: users users_jockey_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_jockey_id_fkey FOREIGN KEY (jockey_id) REFERENCES public.jockeys(id) ON DELETE RESTRICT;


--
-- Name: users users_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.owners(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict LAB8SCHEMA

