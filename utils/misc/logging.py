import logging
import sys

# Windows konsolida o'zbekcha belgilar (‘ ’) kodlash xatosiga sabab bo'lmasin.
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="backslashreplace")

logging.basicConfig(format=u'%(filename)s [LINE:%(lineno)d] #%(levelname)-8s [%(asctime)s]  %(message)s',
                    level=logging.INFO,
                    )
