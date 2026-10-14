-- Additive advisor lineage schema. Existing portfolio/trading tables are untouched.
CREATE TABLE IF NOT EXISTS advisor_decisions (
 advisor_decision_id TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL, context_hash TEXT NOT NULL, authorization_hash TEXT NOT NULL,
 contract_version TEXT NOT NULL, policy_version TEXT NOT NULL,
 structured_json TEXT NOT NULL, rendered_answer TEXT NOT NULL,
 created_at TEXT NOT NULL, valid_until TEXT NOT NULL,
 lifecycle_status TEXT NOT NULL DEFAULT 'VALID'
   CHECK(lifecycle_status IN ('VALID','STALE','SUPERSEDED','EXPIRED')),
 status_reason TEXT, origin TEXT NOT NULL DEFAULT 'advisor',
 learning_eligible INTEGER NOT NULL DEFAULT 0 CHECK(learning_eligible=0)
);
CREATE TRIGGER IF NOT EXISTS advisor_decision_immutable
BEFORE UPDATE OF request_hash,context_hash,authorization_hash,contract_version,policy_version,
 structured_json,rendered_answer,created_at,valid_until,origin,learning_eligible ON advisor_decisions
BEGIN SELECT RAISE(ABORT,'immutable advisor decision'); END;
CREATE TRIGGER IF NOT EXISTS advisor_decision_no_reactivation
BEFORE UPDATE OF lifecycle_status ON advisor_decisions
WHEN OLD.lifecycle_status != 'VALID' AND NEW.lifecycle_status = 'VALID'
BEGIN SELECT RAISE(ABORT,'advisor recomputation requires a new decision id'); END;

CREATE TRIGGER IF NOT EXISTS advisor_decision_no_delete
BEFORE DELETE ON advisor_decisions
BEGIN SELECT RAISE(ABORT,'advisor history is immutable'); END;

CREATE TRIGGER IF NOT EXISTS advisor_decision_identity_immutable
BEFORE UPDATE OF advisor_decision_id ON advisor_decisions
BEGIN SELECT RAISE(ABORT,'immutable advisor decision identity'); END;
