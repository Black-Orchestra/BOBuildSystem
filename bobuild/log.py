from loguru import logger

# TODO: use logrotate on Linux if we run this as a service?

# logger.remove()
logger.add("hg.log", rotation="10 MB", retention=5)
