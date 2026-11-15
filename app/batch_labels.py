"""Readable batch names, separate from the stable identifiers used in handoffs."""


def import_mode(job):
    return job.import_mode or ('manual' if job.kind in ('reserve','sample','file') else 'automatic')


def batch_labels(job):
    mode=import_mode(job)
    return {'import_mode':mode,'display_code':f'{"M" if mode=="manual" else "A"}-{job.id:06d}',
            'is_simulated':bool(job.is_simulated or job.kind=='demo')}
