"""test.opt files processing.

This package provides a single class called OptFileParse which process the
test.opt files. These files are used mainly to tweak tests depending on the
context.
"""

import re
import logging
import os.path


# Regexp that matches valid lines in test.opt files
OPTLINE_REGEXPS = re.compile(r"^([^\s]+)(\s+([a-zA-Z0-9_-]+)(\s+(.*))?)?$")


class BadFormattingError(Exception):
    """Raised when an input line is not correctly formatted."""

    pass


TAGS = 0
ARG = 1
OVERIDABLE = 2

logger = logging.getLogger("optfileparser")


class OptFileParse:
    """test.opt parser.

    ATTRIBUTES
      system_tags: the list of tags applied to the test.opt
      is_dead: True if the test should be considered DEAD, False otherwise
    """

    def __init__(self, system_tags, filename):
        """Parse a test.opt file.

        :param system_tags: either a list of tags or a string containing the
            list of tags separated by commas
        :type system_tags: str | list[str]
        :param filename: the test.opt to be parsed. If this is a string then
            the argument is a filename otherwise if this is a list we consider
            it is the content of the .opt file
        :type filename: str | list[str]
        """
        if isinstance(system_tags, str):
            self.system_tags = system_tags.lower().split(",")
        else:
            self.system_tags = []
            for tag in system_tags:
                self.system_tags.append(tag.lower())
        # Append 'all' to system tags
        if "all" not in system_tags:
            self.system_tags.append("all")

        self.is_dead = False
        self.__note = None
        self.__enable_note = False
        self.__matches = {}
        self.__parse_file(filename)

    def get_value(self, cmd, default_value=None):
        """Query on the parsing result.

        :param cmd: the command on which we do the query ex: dead, cmd, out...
        :type cmd: str
        :param default_value: value returned by default
        :type default_value: str | None

        :return: a string or default value (None by default)
        :rtype: str | None

        by default the query will return ``default_value`` if there is no
        entry for the selected command.
        """
        cmd = cmd.lower()

        if self.is_dead:
            if cmd == "dead":
                return self.__matches[cmd][ARG]
            else:
                return default_value

        if cmd in self.__matches and cmd != "dead":
            return self.__matches[cmd][ARG]
        else:
            return default_value

    def get_values(self, default_values):
        """Query on the parsing result.

        :param default_values: a dictionary for which keys are the commands on
            which we do the query and the associated default values.
        :type default_values: dict

        :return: a dictionary containing the resulting value for each command
        :rtype: dict

        Doing ``get_values({"CMD": "test.cmd", "OUT": "test.out"})`` is
        equivalent to do::

            get_value("CMD", "test.cmd")
            get_value("OUT", "test.out")
        """
        result = {}
        for key in default_values:
            result[key] = self.get_value(key, default_values[key])
        return result

    def get_note(self, sep=None):
        """Get the note.

        :param sep: string used to join the activating tags. Default is ",".
            If "" is specified then a list is returned.
        :type sep: str

        :return: a string (list of tags responsible for the activation of the
            test) is sep is not "" or a list.
        :rtype: str | list[str]

        If there is no note then "" or [] is returned depending on the sep
        value
        """
        if sep is None:
            sep = ","

        if len(sep) == 0:
            if self.__note is not None and not self.is_dead:
                return self.__note[TAGS]
            else:
                return []
        else:
            if self.__note is not None and not self.is_dead:
                return ",".join(self.__note[TAGS])
            else:
                return ""

    # INTERNAL FUNCTIONS
    def __process_opt_line(self, line):
        """process one line of a test.opt type file.

        :type line: string

        :raise BadFormattingError: in case the line cannot be parsed

        The format of each line is the following::

            tag1,tag2,tag3,...,tagN [COMMAND [PARAMETERS]]

        if no COMMAND is given then we assume that the command is 'DEAD false'
        """
        # Remove comments (Ada style) and trailing white characters
        processed_line = re.sub("--.*$", "", line).rstrip()

        # Line contains only comments and/or white characters so ignore it
        if not processed_line:
            return

        m = OPTLINE_REGEXPS.match(processed_line)
        if m is None:
            raise BadFormattingError("Can not parse line: " + line)

        # find command, tags and argument
        tags = m.group(1).split(",")

        if m.group(3):
            # Check for command
            cmd = m.group(3).lower()
            if m.group(4):
                # Get optional argument
                arg = m.group(5)
            else:
                arg = ""
        else:
            # If no command is set then the implicit command is: dead="false"
            cmd = "dead"
            arg = "false"

        if arg == "" and cmd == "dead":
            arg = "true"

        # Enable note only if a dead all is encountered
        if arg != "false" and cmd == "dead" and self.__is_all(tags):
            self.__enable_note = True

        if cmd != "required" and self.__match(tags):
            logger.debug("match: " + cmd + ", tags=" + "%s" % tags)
            if self.__is_overidable(cmd):
                self.__matches[cmd] = (tags, arg, self.__is_all(tags))

                if (
                    not self.__is_dead_cmd(cmd)
                    and (
                        self.__note is None
                        or self.__matches[cmd][OVERIDABLE]
                    )
                ):
                    self.__note = self.__matches[cmd]

        elif cmd == "required" and not self.__match(tags):
            self.__matches["required"] = (tags, arg, False)

    def __is_overidable(self, cmd):
        return cmd not in self.__matches or \
            self.__matches[cmd][OVERIDABLE]

    @classmethod
    def __is_all(cls, tag_list):
        return len(tag_list) == 1 and tag_list[0].lower() == "all"

    def __is_dead_cmd(self, cmd):
        return cmd == "dead" and \
            "dead" in self.__matches and \
            self.__matches["dead"][ARG] != "false"

    def __match(self, tag_list):
        """Match tags against the system tags.

        True if all non-negated tags and none of the negated tags in the given
        list are present in system tags.
        """
        for tag in tag_list:
            if not tag.startswith("!"):
                # If tag is non-negated, it must be present in system tags
                if not (tag.lower() in self.system_tags):
                    return False
            else:
                # If tag is negated, it must be absent from system tags
                if tag[1:].lower() in self.system_tags:
                    return False
        return True

    def __parse_file(self, filename):
        have_opt_data = False
        if isinstance(filename, list):
            for line in filename:
                self.__process_opt_line(line)
            have_opt_data = True
        elif os.path.isfile(filename):
            with open(filename, "r") as optfile:
                for line in optfile:
                    self.__process_opt_line(line)
            have_opt_data = True

        if have_opt_data:
            if "required" in self.__matches:
                self.__matches["dead"] = self.__matches["required"]
                self.is_dead = True
            elif self.__note is not None:
                self.is_dead = False
            elif self.__is_dead_cmd("dead"):
                self.is_dead = True
            else:
                self.is_dead = False

            if (self.__note is not None and self.__note[OVERIDABLE]) \
                    or not self.__enable_note:
                self.__note = None

    def __str__(self):
        result = ""

        if self.is_dead:
            result += 'dead="{}"\n'.format(
                re.sub('"', '\\"', self.__matches["dead"][ARG])
            )
        else:
            for k in self.__matches:
                if k != "dead":
                    result += '{}="{}"\n'.format(
                        k,
                        re.sub('"', '\\"', self.__matches[k][ARG])
                    )

            if self.__note is not None:
                result += 'activating_tag="{}"\n'.format(
                    re.sub('"', '\\"', ",".join(self.__note[TAGS]))
                )

        result = result.rstrip()
        return result
