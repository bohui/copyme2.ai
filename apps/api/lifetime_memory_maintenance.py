"""Bounded non-model maintenance through the existing trusted worker broker."""


async def drain_lifetime_obligations_once(broker, *, limit=4):
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('Maintenance drain accepts one to thirty-two obligations')
    # Generation pause deliberately does not suspend required canonical metadata.
    # The SQL function derives authority from queued rows; no user JWT or owner
    # supplied by a client can select a different tenant here.
    return await broker.rpc('drain_lifetime_memory_obligations',p_limit=limit)
