def revoke_tokens(strategy, entries, user, *args, **kwargs):
    # revoke_tokens = strategy.setting('REVOKE_TOKENS_ON_DISCONNECT', False)
    if revoke_tokens:
        for entry in entries:
            if entry.actual_access_token:
                backend = entry.get_backend_instance(strategy)
                backend.revoke_token(entry.actual_access_token,
                                     entry.uid, user_id=user)
