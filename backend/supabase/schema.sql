-- 사고사례 판단 훈련: Supabase(PostgreSQL) 스키마.
-- 적용: Supabase 대시보드 SQL Editor에 붙여 넣고 실행하거나, backend/에서 python scripts/init_db.py
-- 여러 번 실행해도 된다 (if not exists / on conflict).

-- 유사사고 검색용 벡터 (pgvector)
create extension if not exists vector;

-- 보고서 한 건 = 한 줄. 처리 단계마다 jsonb 칸이 채워진다.
create table if not exists public.reports (
  id          text primary key,                    -- PDF 내용 sha1 앞 10자리 (같은 파일 = 같은 id)
  filename    text not null default '',
  state       text not null default 'queued',      -- status.state 복사본 (목록·필터용)
  status      jsonb not null default cast('{}' as jsonb),  -- {state, message, filename, ingested_at}
  parsed      jsonb,                               -- {pages: ["[p.N]\n…"], sections: {…}}  근거 확인용
  record      jsonb,                               -- 구조화된 사고 정보 (AccidentRecord)
  scenario    jsonb,                               -- 판단 훈련 시나리오 (교관 편집 포함)
  ingested_at timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists reports_ingested_at_idx on public.reports (ingested_at desc);

-- 검색 조각 (개요·원인·권고·본문 …) + 임베딩.
-- 차원을 고정하지 않는다 (EMBED_MODEL을 바꿔도 테이블은 그대로, 대신 /api/reindex 필요).
-- 보고서 수백 건 규모는 인덱스 없이 전수 비교로 충분하다.
create table if not exists public.report_chunks (
  id         text primary key,                     -- "<report_id>:<번호>"
  report_id  text not null references public.reports(id) on delete cascade,
  title      text not null default '',
  kind       text not null,                        -- 개요 | 경위 | 직접원인 | 기여요인 | 규정 | 안전권고 | 교육지적 | 본문
  page       integer,                              -- 원문 쪽 번호 (없으면 null)
  text       text not null,
  embedding  vector not null
);
create index if not exists report_chunks_report_id_idx on public.report_chunks (report_id);

-- 브라우저(anon key)로는 직접 읽고 쓰지 못하게 막는다. 백엔드는 DATABASE_URL(postgres 역할)로 접속해서 영향 없음.
alter table public.reports enable row level security;
alter table public.report_chunks enable row level security;

-- 원문 PDF 보관용 비공개 버킷. 백엔드가 service_role 키로 올리고 내려받는다.
insert into storage.buckets (id, name, public)
values ('reports', 'reports', false)
on conflict (id) do nothing;
