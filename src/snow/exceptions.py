class NoResults(Exception):
    """A query expected one record but found none."""


class MultipleResults(Exception):
    """A query expected one record but found more than one."""
