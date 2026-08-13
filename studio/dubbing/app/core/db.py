"""
Database module for Dubbing Engine.

Single backend: Convex. Supabase cutover complete.
"""
import logging

logger = logging.getLogger(__name__)

logger.info("[DATABASE] Convex backend active")

from app.core import database_convex as backend

# Re-export all database methods and client getters
_get_service_role_client = backend._get_service_role_client
get_user_client = getattr(backend, "get_user_client", lambda *args, **kwargs: None)
reset_client_for_testing = backend.reset_client_for_testing
init_db = backend.init_db
create_job = backend.create_job
get_job = backend.get_job
list_jobs = backend.list_jobs
update_job_status = backend.update_job_status
create_chunk = backend.create_chunk
update_chunk = backend.update_chunk
log_ai_usage = backend.log_ai_usage
get_workspace_minutes = backend.get_workspace_minutes
add_workspace_minutes = backend.add_workspace_minutes
deduct_workspace_minutes = backend.deduct_workspace_minutes
add_transaction = backend.add_transaction
transaction_exists = backend.transaction_exists
list_transactions = backend.list_transactions
create_step_telemetry = backend.create_step_telemetry
update_job_cost = backend.update_job_cost
_internal_args = backend._internal_args
process_payment_success_atomic = backend.process_payment_success_atomic
