import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import format_check as fmt
import style_check as style
from _shared import changes, emit, read_json


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.body = '원고의 청구에 관하여 판단한다.\n\n주어진 사실을 검토한다.'
        self.final = self.root / 'final.txt'
        self.final.write_text('검토서\n'+self.body, encoding='utf-8')
        self.form = {'document_type': 'opinion', 'source': 'user-confirmed-form',
                     'fields': [{'name': 'title', 'value': '검토서'}]}

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self):
        return fmt.inspect(self.final, self.body, self.form)

    def kinds(self, result):
        return {r['kind'] for r in result['issues']}

    def test_normal_document(self):
        result = self.run_check()
        self.assertEqual(result['status'], 'mechanical_checks_complete')
        self.assertEqual(result['page_review'], 'final_document_required')

    def test_required_blank(self):
        self.form['fields'].append({'name': 'party', 'value': ''})
        self.assertIn('value_required', self.kinds(self.run_check()))

    def test_required_false(self):
        self.form['fields'].append({'name': 'party', 'value': '', 'required': False})
        self.assertEqual(self.run_check()['issues'], [])

    def test_conditional_false(self):
        self.form['context'] = {'assigned': False}
        self.form['fields'].append({'name': 'case', 'value': '', 'required_if': {'assigned': True}})
        self.assertEqual(self.run_check()['issues'], [])

    def test_conditional_true(self):
        self.form['context'] = {'assigned': True}
        self.form['fields'].append({'name': 'case', 'value': '', 'required_if': {'assigned': True}})
        self.assertIn('value_required', self.kinds(self.run_check()))

    def test_unknown_condition(self):
        self.form['fields'].append({'name': 'case', 'required_if': {'assigned': True}})
        self.assertIn('condition_required', self.kinds(self.run_check()))

    def test_bad_required_type(self):
        self.form['fields'][0]['required'] = 'false'
        with self.assertRaises(ValueError):
            self.run_check()

    def test_duplicate_field(self):
        self.form['fields'] *= 2
        with self.assertRaises(ValueError):
            self.run_check()

    def test_missing_form_source(self):
        del self.form['source']
        self.assertIn('form_source', self.kinds(self.run_check()))

    def test_placeholder(self):
        self.final.write_text(self.body+'\n검토서 {{날짜}}', encoding='utf-8')
        self.assertIn('placeholders', self.kinds(self.run_check()))

    def test_removed_body(self):
        self.final.write_text('검토서', encoding='utf-8')
        self.assertIn('body_review', self.kinds(self.run_check()))

    def test_changed_number(self):
        result = fmt.compare_body('대금은 100원이다.', '대금은 200원이다.')
        self.assertEqual(result['status'], 'review_required')

    def test_added_middle_paragraph(self):
        self.final.write_text('검토서\n원고의 청구에 관하여 판단한다.\n새 결론을 추가한다.\n주어진 사실을 검토한다.', encoding='utf-8')
        self.assertIn('body_review', self.kinds(self.run_check()))

    def test_reordered_body(self):
        first, second = self.body.split('\n\n')
        self.assertEqual(fmt.compare_body(self.body, second+first)['status'], 'review_required')

    def test_whitespace_equivalence(self):
        self.assertEqual(fmt.compare_body('법리를 확인한다.', '법 리를\n확인한다.')['status'], 'matched')

    def test_evidence_parts(self):
        self.assertEqual(fmt.evidence('갑 제01호증의 2 및 을제3호증'), {'갑:1:2','을:3'})

    def test_grouped_evidence(self):
        self.assertEqual(fmt.evidence('갑 제1, 2호증 및 을 제3호증'), {'갑:1','갑:2','을:3'})

    def test_grouped_parts(self):
        self.assertEqual(fmt.evidence('갑 제1호증의 1, 2'), {'갑:1:1','갑:1:2'})

    def test_shared_party_evidence(self):
        self.assertEqual(fmt.evidence('갑 제1호증, 제2호증'), {'갑:1','갑:2'})

    def test_evidence_range(self):
        self.assertEqual(fmt.evidence('갑 제1호증 내지 제3호증'), {'갑:1','갑:2','갑:3'})

    def test_large_evidence_range(self):
        with self.assertRaises(ValueError):
            fmt.evidence('갑 제1내지999999999호증')

    def test_grouped_evidence_requires_manifest(self):
        self.body = '갑 제1, 2호증을 확인한다.'
        self.final.write_text('검토서\n'+self.body,encoding='utf-8')
        self.assertIn('attachment_manifest_required',self.kinds(self.run_check()))

    def test_final_only_evidence(self):
        self.final.write_text('검토서\n'+self.body+'\n갑 제2호증 참조.',encoding='utf-8')
        result = self.run_check()
        self.assertIn('unmapped_evidence',self.kinds(result))
        self.assertIn('final_evidence_review',self.kinds(result))

    def test_unrecognized_evidence(self):
        self.body += '\n갑 제1-1호증을 확인한다.'
        self.assertIn('evidence_notation_review',self.kinds(self.run_check()))

    def test_missing_manifest(self):
        self.body += '\n\n갑 제1호증을 확인한다.'
        result = self.run_check()
        self.assertIn('attachment_manifest_required', self.kinds(result))

    def test_missing_attachment_file(self):
        self.body = '갑 제1호증의 2를 확인한다.'
        self.final.write_text('검토서\n'+self.body, encoding='utf-8')
        manifest = self.root/'attachments.json'
        manifest.write_text(json.dumps([{'label':'갑 제1호증의 2','path':'missing.pdf'}]), encoding='utf-8')
        self.assertIn('attachment_file_missing', self.kinds(fmt.inspect(self.final,self.body,self.form,manifest)))

    def test_relative_attachment(self):
        self.body = '갑 제1호증의 2를 확인한다.'
        self.final.write_text('검토서\n'+self.body, encoding='utf-8')
        (self.root/'evidence.txt').write_text('제공된 증거',encoding='utf-8')
        manifest = self.root/'attachments.json'
        manifest.write_text(json.dumps([{'label':'갑 제1호증의 2','path':'evidence.txt'}]), encoding='utf-8')
        self.assertEqual(fmt.inspect(self.final,self.body,self.form,manifest)['issues'], [])

    def test_duplicate_evidence(self):
        manifest = self.root/'attachments.json'
        item = {'label':'갑 제1호증','path':'missing.pdf'}
        manifest.write_text(json.dumps([item,item]), encoding='utf-8')
        self.assertIn('duplicate_evidence', self.kinds(fmt.inspect(self.final,self.body,self.form,manifest)))

    def test_empty_final(self):
        self.final.write_text('', encoding='utf-8')
        self.assertIn('text_extraction', self.kinds(self.run_check()))

    def test_hwp_needs_tool(self):
        self.final = self.root/'final.hwp'
        self.final.write_bytes(b'fixture')
        with self.assertRaises(ImportError):
            self.run_check()

    def test_docx_text(self):
        docx = self.root/'final.docx'
        xml = '<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>검토서</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>표 내용</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
        with zipfile.ZipFile(docx,'w') as z:
            z.writestr('word/document.xml',xml)
        result = fmt.extract_file(docx)
        self.assertIn('검토서\n표 내용',result['text'])
        self.assertEqual(result['page_review'],'render_and_review_required')

    def test_hwpx_natural_order(self):
        hwpx = self.root/'final.hwpx'
        with zipfile.ZipFile(hwpx,'w') as z:
            for i in [10,2,1]:
                z.writestr(f'Contents/section{i}.xml', f'<root><p><t>문단{i}</t></p></root>')
        self.assertEqual(fmt.extract_file(hwpx)['text'], '문단1\n문단2\n문단10')

    def test_pdf_blank_page(self):
        from pypdf import PdfWriter
        pdf = self.root/'final.pdf'
        writer = PdfWriter();writer.add_blank_page(width=612,height=792)
        with pdf.open('wb') as out:
            writer.write(out)
        result = fmt.inspect(pdf,self.body,self.form)
        self.assertIn('page_text_review',self.kinds(result))

    def test_bad_pdf(self):
        pdf = self.root/'bad.pdf'
        pdf.write_bytes(b'%PDF-invalid')
        with self.assertRaises(ValueError):
            fmt.extract_file(pdf)

    def test_attachment_output_protected(self):
        attachment = self.root/'evidence.txt'
        attachment.write_text('원본 증거',encoding='utf-8')
        manifest = self.root/'attachments.json'
        manifest.write_text(json.dumps([{'label':'갑 제1호증','path':'evidence.txt'}]),encoding='utf-8')
        body = self.root/'body.txt'; body.write_text(self.body,encoding='utf-8')
        form = self.root/'form.json'; form.write_text(json.dumps(self.form),encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            code = fmt.main([str(self.final),'--body',str(body),'--form',str(form),'--attachments',str(manifest),'--output',str(attachment)])
        self.assertEqual(code,2)
        self.assertEqual(attachment.read_text(encoding='utf-8'),'원본 증거')

    def test_source_form_output_protected(self):
        source = self.root/'source.txt'; source.write_text('원본 서식',encoding='utf-8')
        self.form['source'] = 'source.txt'
        body = self.root/'body.txt'; body.write_text(self.body,encoding='utf-8')
        form = self.root/'form.json'; form.write_text(json.dumps(self.form),encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            code = fmt.main([str(self.final),'--body',str(body),'--form',str(form),'--output',str(source)])
        self.assertEqual(code,2)
        self.assertEqual(source.read_text(encoding='utf-8'),'원본 서식')

    def test_file_uri_source(self):
        source = self.root/'source form.txt'
        self.assertEqual(fmt.local_source(source.as_uri(),self.root/'form.json'),source)

    def test_package_output_protected(self):
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            emit({}, ROOT/'data'/'style_profiles.json')

    def test_xml_entities(self):
        with self.assertRaises(ValueError):
            fmt.extract_xml_paragraphs(b'<!DOCTYPE x [<!ENTITY a "x">]><p><t>&a;</t></p>')

    def test_output_protects_input(self):
        old = self.final.read_bytes()
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            emit({}, self.final, [self.final])
        self.assertEqual(self.final.read_bytes(),old)


class StyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kiwi = style.analyzer()

    def test_real_morphology(self):
        result = style.extract('원고의 주장은 이유 있다. 따라서 청구를 인용한다.',self.kiwi)
        self.assertGreater(result['counts']['morphs'],0)
        self.assertTrue(any('/' in key for key in result['lexical']))

    def test_same_text_same_metrics(self):
        text = '위 사정을 종합하면 이와 같이 판단함이 타당하다.'
        self.assertEqual(style.extract(text,self.kiwi),style.extract(text,self.kiwi))

    def test_empty_input(self):
        with self.assertRaises(ValueError):
            style.inspect('','civil','judgment',self.kiwi)

    def test_only_quote_needs_body(self):
        with self.assertRaises(ValueError):
            style.inspect('> 인용문만 있다.','civil','judgment',self.kiwi)

    def test_matching_profile(self):
        result = style.inspect('이 사건에 관하여 판단한다. 원고의 주장은 이유 있다.','civil','judgment',self.kiwi)
        self.assertEqual(result['reference'],'matched')
        self.assertEqual(result['status'],'measured')

    def test_other_document_type_shares_domain_reference(self):
        result = style.inspect('준비서면을 제출한다.','civil','brief',self.kiwi)
        self.assertEqual(result['reference'],'matched')
        self.assertEqual(result['reference_group'],'civil')
        self.assertTrue(result['reference_positions'])
        self.assertTrue(result['examples'])

    def test_reference_group_is_domain(self):
        result = style.inspect('이 사건에 관하여 판단한다.','civil','judgment',self.kiwi)
        self.assertEqual(result['reference_group'],'civil')
        self.assertNotIn('reference_note',result)

    def test_examples_fallback_to_domain(self):
        rows = style.get_examples('civil','brief',limit=2)
        self.assertTrue(rows)
        self.assertTrue(all(r['document_type']=='judgment' for r in rows))

    def test_small_group_examples_only(self):
        result = style.inspect('피고인의 주장에 관하여 판단한다.','criminal','judgment',self.kiwi)
        self.assertEqual(result['reference'],'examples_or_user_reference_required')
        self.assertIsNone(result['reference_group'])
        self.assertTrue(result['examples'])

    def test_quoted_text_separate(self):
        result = style.inspect('원고의 주장을 판단한다.\n\n> 인용문의 내용이다.','civil','judgment',self.kiwi)
        self.assertIsNotNone(result['quoted_metrics'])
        self.assertEqual(len(result['paragraphs']),1)

    def test_paragraph_locations(self):
        blocks = style.paragraphs('# 제목\n\n첫 문단이다.\n\n둘째 문단이다.')
        self.assertEqual([p['line'] for p in blocks],[3,5])

    def test_extreme_length_still_measured(self):
        result = style.inspect(('이러한 사정을 참작하여 '*80)+'판단한다.','civil','judgment',self.kiwi)
        self.assertEqual(result['status'],'measured')

    def test_reference_version_mismatch(self):
        with self.assertRaises(ValueError):
            style.inspect('문장이다.','civil','judgment',self.kiwi,{'extractor':'other'})

    def test_examples_filter(self):
        rows = style.get_examples('civil','judgment',pattern='P01',limit=2)
        self.assertTrue(rows)
        self.assertLessEqual(len(rows),2)
        self.assertTrue(all('text' in r and 'url' not in r for r in rows))

    def test_semantic_word_change_is_exposed(self):
        result = changes('예외가 적용된다.','예외가 적용되지 않는다.')
        self.assertTrue(result['changed'])
        self.assertIn('않는다',result['blocks'][0]['after'])

    def test_numbers_and_names(self):
        result = changes('원고 가는 100원을 청구한다.','원고 나는 200원을 청구한다.',['원고 가'])
        self.assertIn('numbers',result['changed_values'])
        self.assertEqual(result['anchor_changes'],['원고 가'])

    def test_anchor_input_array(self):
        with self.assertRaises(ValueError):
            changes('원고 가','원고 나',{'party':'원고 가'})

    def test_cli_needs_output(self):
        result = subprocess.run([sys.executable,str(ROOT/'scripts'/'style_check.py'),'check','x.txt','--domain','civil'],capture_output=True)
        self.assertEqual(result.returncode,2)


if __name__ == '__main__':
    unittest.main()
