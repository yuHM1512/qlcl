-- Idempotency keys for QC input writes (2026-11-25)
-- Client sinh client_request_id (UUID) cho mỗi lần lưu; server bỏ qua bản gửi lại trùng id.

CREATE TABLE IF NOT EXISTS public.qc_client_request (
    request_id  TEXT PRIMARY KEY,
    endpoint    TEXT NOT NULL,
    response    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_client_request_created_at
    ON public.qc_client_request(created_at);
