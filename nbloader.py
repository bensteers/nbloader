import os
import io
import mistune

from nbformat import reader, converter, current_nbformat
from IPython.core.interactiveshell import InteractiveShell
from IPython import get_ipython


def new_interactive_shell(user_ns=None):
    # TODO: I still haven't figured out how to get this to properly work with matplotlib inline

    # See: https://github.com/ipython/ipykernel/blob/fe52dbd726cb405eb3a1e74e6a7fdb32372150ed/ipykernel/ipkernel.py#L63
    # See: https://github.com/ipython/ipython/blob/23e025315441869b3a62bd6652703780aecfefdb/IPython/core/interactiveshell.py#L1290
    # output capturing: https://github.com/jupyter-widgets/ipywidgets/blob/36fe37594cd5a268def228709ca27e37b99ac606/ipywidgets/widgets/widget_output.py#L107
    # loading notebooks as modules: https://github.com/jupyter/notebook/blob/b8b66332e2023e83d2ee04f83d8814f567e01a4e/docs/source/examples/Notebook/Importing%20Notebooks.ipynb


    # ip = get_ipython()
    # shell = ip.__class__(parent=ip.parent,
    #     profile_dir=ip.profile_dir,
    #     user_ns=user_ns,
    #     kernel=ip.kernel,
    # )
    # shell.displayhook.session = ip.displayhook.session
    # shell.displayhook.pub_socket = ip.displayhook.pub_socket
    # shell.displayhook.topic = ip.displayhook.topic
    # shell.display_pub.session = ip.display_pub.session
    # shell.display_pub.pub_socket = ip.display_pub.pub_socket

    shell = InteractiveShell(user_ns=user_ns)
    return shell


class Notebook(object):

    blacklist = ['__skip__']

    def __init__(self, nb_path, ns=None, tag_md=True, nb_dir=None,
                 interactive=False, display_last_line=None, show_md=False):
        self.nb_path = nb_path

        # markdown
        self.tag_md = tag_md
        self.show_md = show_md
        if show_md:
            raise NotImplementedError('We cannot currently display markdown output.')
        if tag_md:
            self.md_parser = mistune.Markdown()

        # running directory
        if nb_dir is None:
            nb_dir = os.path.dirname(self.nb_path)
        self.nb_dir = nb_dir

        self.interactive = interactive
        ip = get_ipython()
        if interactive: # use the current namespace / environment
            self.shell = ip
            if ns:
                self.shell.push(ns) # add ns to current shell (accessible in globals)

        else: # create an isolated environment
            self.shell = new_interactive_shell(ns)

            if display_last_line is False:
                self.shell.ast_node_interactivity = 'none'
            if nb_dir:
                self.shell.run_cell('import os;os.chdir("{}")'.format(nb_dir))

        self.ns = self.shell.user_ns

        self.refresh()
        self.run_tag('__init__', strict=False)

    def restart(self):
        if self.interactive:
            raise Exception('Restarting an interactive session would mean restarting the current notebook.')
        self.shell.reset()

    def refresh(self):
        self.cells = []
        self.md_tags = []
        self.block_tag = None

        with io.open(self.nb_path, 'r', encoding='utf-8') as f:
            notebook = reader.read(f)

        # convert to current notebook version
        notebook = converter.convert(notebook, current_nbformat)

        for i, cell in enumerate(notebook.cells):
            if cell.cell_type == 'markdown' and self.tag_md:
                # tokenize markdown block
                tokens = self.md_parser.block(cell.source, rules=['heading', 'lheading'])

                for tok in tokens:
                    if tok['type'] == 'heading':
                        # filter out smaller headings and add new heading
                        new_level, tag = tok['level'], tok['text']
                        self.md_tags = [
                            (lvl, tag) for lvl, tag in self.md_tags
                            if lvl < new_level
                        ]
                        self.md_tags.append((new_level, tag))

                if self.show_md:
                    self.cells.append({'source': cell.source, 'cell_type': cell.cell_type, 'tags': self._cell_tags(cell)})
            elif cell.cell_type == 'code':
                self.cells.append({'source': cell.source, 'cell_type': cell.cell_type, 'tags': self._cell_tags(cell)})

    def _run(self, cells):
        if self.interactive and self.nb_dir:
            cwd = os.getcwd()
            os.chdir(self.nb_dir)

        # if not self.interactive:
        #     ns_ = self.shell.user_ns
        #     self.shell.user_ns = self.ns

        try:
            for cell in cells:
                self.shell.run_cell(cell['source'])
        finally:
            if self.interactive and self.nb_dir:
                os.chdir(cwd)

            # if not self.interactive:
            #     self.shell.user_ns = ns_

        return self

    def run_all(self, blacklist=None):
        if blacklist is False: # disable blacklist
            blacklist = []
        else:
            if isinstance(blacklist, str):
                blacklist = [blacklist]
            elif blacklist is None:
                blacklist = []

            blacklist += self.blacklist # merge blacklist

        cells = [
            cell for cell in self.cells
            if not any(tag in cell['tags'] for tag in blacklist)
        ]

        self._run(cells)
        return self

    def run_cells(self):
        raise NotImplementedError()

    def _cell_tags(self, cell):
        tags = []

        tags = cell.metadata.get('tags', [])

        for level, tag in self.md_tags:
            # can access either through heading text
            # or with level specified using markdown syntax
            tags.append(tag)
            tags.append('#' * level + ' ' + tag)

        if self.block_tag:
            tags.append(self.block_tag)

        if cell.cell_type == 'code':
            if cell.source and cell.source[0] == '#':
                first_line = cell.source.split('\n', 1)[0]

                if first_line.startswith('##block '): # start block ttag
                    first_line = first_line[8:].strip()
                    self.block_tag = first_line
                    tags.append(first_line)

                elif first_line.startswith('##lastblock'): # end block tag
                    self.block_tag = None

                else: # line tag
                    first_line = first_line.strip('#').strip()
                    tags.extend(first_line.split())

        return tags or [None]

    def run_tag(self, tag, strict=True):
        cells = [cell for cell in self.cells if tag in cell['tags']]

        if cells:
            self._run(cells)
        else:
            assert not strict, 'Tag "{}" found'.format(tag)
        return self

    def run_before(self, tag, strict=True):
        try:
            i = next(i for i, cell in enumerate(self.cells) if tag in cell['tags'])
            if i > 0: # if i is zero, it's the first one and there's no cells before.
                self._run(cells[:i])
        except StopIteration:
            assert not strict, 'Tag "{}" found'.format(tag)
        return self

    def run_after(self, tag, strict=True):
        try:
            i = next(i for i, cell in enumerate(self.cells[::-1]) if tag in cell['tags'])
            if i > 0: # if i is zero, it's the last one and there's no cells after.
                self._run(cells[-i:])
        except StopIteration:
            assert not strict, 'Tag "{}" found'.format(tag)
        return self

    def __del__(self):
        self.run_tag('__del__', strict=False)

    def __getstate__(self):
        return (self.nb_path, self.ns)

    def __setstate__(self, d):
        self.nb_path, self.ns = d
