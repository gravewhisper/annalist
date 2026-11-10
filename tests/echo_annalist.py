import dataclasses
import re
import sys

from annalist import backends, cli

ECHO = "ECHO"
scripted = backends.Fake.complete


def complete(self, request):
    reply = scripted(self, request)
    words = " ".join(sorted(set(re.findall(r"[^\W\d_]+", request.prompt))))
    return dataclasses.replace(reply, text=reply.text.replace(ECHO, words))


if __name__ == "__main__":
    backends.Fake.complete = complete
    sys.argv[0] = "annalist"
    cli.main()
