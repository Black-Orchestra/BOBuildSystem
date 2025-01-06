# Similar to https://github.com/tuokri/udk_configparser.

import configparser
from typing import Any


class MultiValueConfigDict(dict):
    def __setitem__(self, key: Any, value: Any):
        if key in self and isinstance(value, list):
            self[key].extend(value)
        else:
            super().__setitem__(key, value)


class MultiConfigParser(configparser.ConfigParser):
    """Allows duplicated keys in config files."""

    def __init__(self,
                 *args,
                 strict=False,
                 dict_type=MultiValueConfigDict,
                 converters=None,
                 comment_prefixes=";",
                 allow_no_value=True,
                 **kwargs):

        if converters is None:
            converters = {
                "list": MultiConfigParser.getlist,
            }
        super().__init__(
            *args,
            strict=strict,
            dict_type=dict_type,
            converters=converters,
            comment_prefixes=comment_prefixes,
            allow_no_value=allow_no_value,
            **kwargs,
        )
        self.optionxform = str

    @staticmethod
    def getlist(value: str) -> list[str]:
        value = value.replace("\r", "")
        return value.split("\n")

    def _write_section(self, fp, section_name, section_items, delimiter):
        fp.write("[{}]\n".format(section_name))
        for key, value in section_items:
            value = self._interpolation.before_write(
                self, section_name, key, value)
            if value is not None or not self._allow_no_value:
                if str(value).count("\n") >= 1:
                    # Multi value case.
                    split = str(value).split("\n")
                    first = split[0]
                    rest = split[1:]
                    first = "{delimiter}{first}\n{key}{delimiter}".format(
                        delimiter=delimiter,
                        first=first,
                        key=key,
                    )
                    rest = "\n{key}{delimiter}".format(
                        key=key,
                        delimiter=delimiter,
                    ).join(rest)
                    value = first + rest
                else:
                    # TODO: what the heck is this?
                    value = delimiter + str(value).replace("\n", "\n\t")
            else:
                value = ""
            fp.write("{}{}\n".format(key, value))
        fp.write("\n")
