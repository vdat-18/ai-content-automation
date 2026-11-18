"""A product can have many videos: each one is a project whose id is the product id plus a suffix.

Everything made for one video (brief, images, clips, voice, video) is stored under its project id.
A project id without a suffix is the first video of the product, made before there were many.
"""

SEPARATOR = "-v"


def product_of(project_id: str) -> str:
    """The product a project (one video) belongs to."""
    return project_id.partition(SEPARATOR)[0]
