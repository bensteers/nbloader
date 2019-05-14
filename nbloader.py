import os
import io

import mistune

from nbformat import reader, converter, current_nbformat
from IPython.core.interactiveshell import InteractiveShell
from IPython import get_ipython
from IPython.core.compilerop import CachingCompiler

class NotImplementedError(Exception):
    pass

class Notebook(object):

    blacklist = ['__skip__']

    def __init__(self, nb_path, ns=None, tag_md=True, nb_dir=None):
        self.nb_path = nb_path

        # markdown
        self.tag_md = tag_md
        if tag_md:
            self.md_parser = mistune.Markdown()

        if nb_dir is None:
            nb_dir = os.path.dirname(self.nb_path)
        self.nb_dir = nb_dir

        self.restart(ns)
        self.shell = get_ipython()
        self.refresh()
        self.run_tag('__init__', strict=False)

    def restart(self, ns=None):
        self.ns = ns or dict()

    def refresh(self):
        self.cells = []
        self.md_tags = []
        self.block_tag = None

        with io.open(self.nb_path, 'r', encoding='utf-8') as f:
            notebook = reader.read(f)

        # convert to current notebook version
        notebook = converter.convert(notebook, current_nbformat)

        compiler = CachingCompiler()
        for i, cell in enumerate(notebook.cells):
            if cell.cell_type == 'markdown' and self.tag_md:
                # tokenize markdown block
                tokens = self.md_parser.block(cell.source)
                for tok in tokens:
                    if tok['type'] == 'heading':
                        # filter out smaller headings and add new heading
                        new_level, tag = tok['level'], tok['text']
                        self.md_tags = [
                            (lvl, tag) for lvl, tag in self.md_tags
                            if lvl < new_level
                        ]
                        self.md_tags.append((new_level, tag))

            elif cell.cell_type == 'code':
                # translate all magic % commands to code
                source = self.shell.input_transformer_manager.transform_cell(cell.source)
                # need to use this cell_name so it gives a nice debug information from the notebook
                cell_name = compiler.cache(source, i)
                # compile the code
                source = compile(source, cell_name, 'exec')

                self.cells.append({'code': source, 'tags': self._cell_tags(cell)})

    def _run(self, cells):
        cwd = os.getcwd()
        if self.nb_dir:
            os.chdir(self.nb_dir)

        try:
            for cell in cells:
                exec(cell['code'], self.ns)
        finally:
            os.chdir(cwd)

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
