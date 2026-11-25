-- 앱 전용 DB 역할 (schema.sql 다음에 적용). postgres(관리자) 비밀번호 없이 앱을 접속시키기 위한 최소 권한 역할.
-- reports·report_chunks 두 테이블만 읽고 쓸 수 있다. 같은 프로젝트의 다른 테이블에는 권한이 없다.
-- 실행할 때 :'app_password' 두 곳을 '비밀번호'(작은따옴표 포함)로 바꾼다. 비밀번호는 .env에만 두고 깃에 올리지 않는다.
-- 접속 문자열 (Session pooler):
--   postgresql://accident_trainer.<project-ref>:<비밀번호>@aws-0-<region>.pooler.supabase.com:5432/postgres

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'accident_trainer') then
    create role accident_trainer login password :'app_password';
  else
    alter role accident_trainer with login password :'app_password';
  end if;
end $$;

grant usage on schema public to accident_trainer;
grant select, insert, update, delete on public.reports, public.report_chunks to accident_trainer;

-- 두 테이블은 RLS가 켜져 있으므로 이 역할에만 전체 접근 정책을 연다 (브라우저용 anon 키는 여전히 막힘)
drop policy if exists accident_trainer_all on public.reports;
create policy accident_trainer_all on public.reports for all to accident_trainer using (true) with check (true);
drop policy if exists accident_trainer_all on public.report_chunks;
create policy accident_trainer_all on public.report_chunks for all to accident_trainer using (true) with check (true);
