import io

import pandas as pd
import pytest

from datadoctor.core import CleanOptions, DataDoctorError, analyze, clean, export_table, load_table


def test_csv_utf8_semicolon_and_leading_zeros():
    df = load_table('id;price;name\n001;10;A\n002;;B\n002;;B\n'.encode(), 'sample.csv')
    assert df['id'].iloc[0] == '001'
    report = analyze(df)
    assert report['summary']['duplicate_rows'] == 1
    assert report['summary']['missing_cells'] == 2
    assert next(c for c in report['columns'] if c['name'] == 'id')['type'] == 'text'


def test_blank_text_is_missing_and_safe_clean():
    df = load_table(b'name,price\nAlice,10\nBob, \nCarl,20\n', 'x.csv')
    assert analyze(df)['summary']['missing_cells'] == 1
    result, actions = clean(df, CleanOptions(missing_strategy='fill'))
    assert actions['missing_cells_filled'] == 1
    assert result.loc[1, 'price'] == '15'


def test_outliers_and_opt_in_capping():
    df = load_table(b'amount\n10\n11\n12\n13\n14\n300\n', 'x.csv')
    report = analyze(df)
    assert report['summary']['outlier_cells'] == 1
    same, _ = clean(df, CleanOptions(drop_duplicates=False))
    assert same.loc[5, 'amount'] == '300'
    fixed, actions = clean(df, CleanOptions(cap_outliers=True))
    assert actions['outliers_capped'] == 1
    assert float(fixed.loc[5, 'amount']) < 300


def test_duplicate_and_drop_rows():
    df = load_table(b'first,last\nA,1\nA,1\nB,\nC,3\n', 'test.csv')
    cleaned, actions = clean(df, CleanOptions(missing_strategy='drop_rows'))
    assert actions['duplicates_removed'] == 1
    assert actions['missing_rows_removed'] == 1
    assert len(cleaned) == 2


def test_excel_roundtrip():
    original = pd.DataFrame({'a':[1, 2], 'b':['Hello', 'World']})
    raw = io.BytesIO()
    original.to_excel(raw, index=False)
    loaded = load_table(raw.getvalue(), 'data.xlsx')
    assert loaded['a'].iloc[0] == 1
    blob, mime = export_table(loaded, '.xlsx')
    assert blob[:2] == b'PK'
    assert 'spreadsheetml' in mime


def test_csv_formula_escape():
    df = pd.DataFrame({'comment':['=HYPERLINK("evil")', '+SUM(1)', '@ABC', 'safe'], 'value':[1,2,3,4]})
    content, _ = export_table(df, '.csv')
    text = content.decode('utf-8-sig')
    assert "'=HYPERLINK" in text
    assert "'+SUM" in text
    assert "'@ABC" in text
    assert '\nsafe,4' in text


def test_unsupported_and_invalid_inputs():
    with pytest.raises(DataDoctorError):
        load_table(b'stuff', 'x.xls')
    with pytest.raises(DataDoctorError):
        load_table(b'\xff', 'x.csv')
    with pytest.raises(DataDoctorError):
        load_table(b'not zip', 'x.xlsx')
    with pytest.raises(DataDoctorError):
        CleanOptions(missing_strategy='unknown')


def test_no_imputation_on_all_missing_column():
    df = load_table(b'a,b\n1,\n2,\n3,\n', 'x.csv')
    result, actions = clean(df, CleanOptions(missing_strategy='fill'))
    assert result['b'].isna().all()
    assert actions['missing_cells_filled'] == 0


def test_empty_table_report():
    df = load_table(b'a,b\n', 'x.csv')
    assert analyze(df)['summary']['rows'] == 0


def test_csv_to_xlsx_output():
    df = load_table(b'name,value\nAlice,10\n', 'x.csv')
    raw, _ = export_table(df, '.xlsx')
    assert len(raw) > 100


def test_negative_numeric_preserved_and_formula_header_escaped():
    df = load_table(b'=danger,value\nplain,-2.5\n', 'danger.csv')
    raw, _ = export_table(df, '.csv')
    decoded = raw.decode('utf-8-sig')
    assert decoded.startswith("'=danger,value")
    assert 'plain,-2.5' in decoded


def test_nonfinite_numeric_column_is_not_analyzed_as_number():
    df = load_table(b'amount\n1\ninf\n3\n', 'data.csv')
    result = analyze(df)
    assert result['columns'][0]['type'] == 'text'


def test_xlsx_formula_like_text_is_exported_as_text():
    from openpyxl import load_workbook
    df = pd.DataFrame({'formula': ['=HYPERLINK("https://example.com")', '+CMD()', '@SUM(2)', 'normal']})
    raw, _ = export_table(df, '.xlsx')
    sheet = load_workbook(io.BytesIO(raw), data_only=False).active
    for row in range(2, 5):
        cell = sheet.cell(row, 1)
        assert cell.data_type != 'f'
        assert cell.value.startswith("'")
    assert sheet.cell(5, 1).value == 'normal'
