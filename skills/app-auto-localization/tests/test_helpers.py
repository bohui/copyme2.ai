from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_catalogs import load_catalog, compare, argument_names
from inventory import inventory

class CatalogueTests(unittest.TestCase):
    def read(self, content):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'messages.json'
            path.write_text(content, encoding='utf-8')
            return load_catalog(path)
    def test_nested(self):
        self.assertEqual(self.read('{"Common":{"save":"Save"}}'), {'Common.save':'Save'})
    def test_duplicate(self):
        with self.assertRaises(ValueError): self.read('{"save":"A","save":"B"}')
    def test_dotted_key(self):
        with self.assertRaises(ValueError): self.read('{"Common.save":"Save"}')
    def test_empty_message(self):
        with self.assertRaises(ValueError): self.read('{"save":" "}')
    def test_non_string_leaf(self):
        with self.assertRaises(ValueError): self.read('{"save":22}')
    def test_array(self):
        with self.assertRaises(ValueError): self.read('{"save":["A"]}')
    def test_missing_extra(self):
        self.assertEqual([x['kind'] for x in compare({'a':'A'},{'b':'B'})],['missing_key','extra_key'])
    def test_argument_mismatch(self):
        self.assertEqual(compare({'a':'{name}'},{'a':'{other}'})[0]['kind'],'argument_name_mismatch')
    def test_unicode_messages(self):
        self.assertEqual(compare({'save':'Save'},{'save':'保存'}), [])
    def test_plural_names(self):
        self.assertEqual(argument_names('{count, plural, one {# memory} other {# memories}}'), {'count'})
    def test_bundled_catalogues(self):
        root=Path(__file__).resolve().parents[1]/'assets'/'messages'
        self.assertEqual(compare(load_catalog(root/'en-AU.json'),load_catalog(root/'zh-CN.json')),[])

class InventoryTests(unittest.TestCase):
    def test_does_not_emit_source_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'page.tsx').write_text('<button>PRIVATE EXAMPLE TEXT</button>',encoding='utf-8')
            result=inventory(root)
            self.assertNotIn('PRIVATE EXAMPLE TEXT',json.dumps(result))
            self.assertEqual(result['findings'][0]['line'],1)
    def test_skips_sensitive_and_generated_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for folder in ('node_modules','recordings','transcripts','.agents'):
                (root/folder).mkdir()
                (root/folder/'page.tsx').write_text('<button>Private</button>')
            (root/'.env').write_text('SECRET=DO_NOT_EMIT')
            self.assertEqual(inventory(root)['scanned_files'],0)
    def test_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'linked.tsx').symlink_to('/etc/passwd')
            self.assertEqual(inventory(root)['scanned_files'],0)
    def test_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('a.tsx','b.tsx'): (root/name).write_text('<p>Hello</p>')
            result=inventory(root,1)
            self.assertEqual(result['scanned_files'],1)
            self.assertTrue(result['truncated'])
    def test_package_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'package.json').write_text(json.dumps({'dependencies':{'next':'1','secret-name':'x'},'scripts':{'secret':'x'}}))
            result=inventory(root)
            self.assertEqual(result['packages'][0]['dependencies'],{'next':'1'})
            self.assertNotIn('secret-name',json.dumps(result))

if __name__=='__main__': unittest.main()
