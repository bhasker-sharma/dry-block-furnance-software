from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from models.calibration_session import CalibrationSession, InstrumentInfo
from db.settings_store import SettingsStore
from calibration.cmc import interpolate_cmc

# ── palette ───────────────────────────────────────────────────────────
NAVY   = colors.HexColor('#1a2332')
ACCENT = colors.HexColor('#3d7fff')
AMBER  = colors.HexColor('#f59e0b')
GREEN  = colors.HexColor('#22c55e')
RED    = colors.HexColor('#ef4444')
LIGHT  = colors.HexColor('#f7f9fc')
BORDER = colors.HexColor('#d1d9e6')
GREY   = colors.HexColor('#6b7a90')


def generate_pdf(session: CalibrationSession, output_path: Path) -> Path:
    """
    Render a full calibration certificate PDF including instrument details.
    Returns the output path on success.
    """
    settings = SettingsStore().load()
    cmc_enabled = bool(settings.get('cmc_enabled'))
    cmc_points  = settings.get('cmc_points', [])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=16*mm, rightMargin=16*mm,
        topMargin=14*mm,  bottomMargin=14*mm,
    )
    styles = getSampleStyleSheet()
    story  = []

    story.append(_header(session, styles))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 3*mm))
    story.append(_meta_table(session, styles))
    story.append(Spacer(1, 4*mm))
    story.append(KeepTogether([
        _section_title('Instrument Details', styles),
        Spacer(1, 2*mm),
        _instrument_table(session, styles),
    ]))
    story.append(Spacer(1, 4*mm))
    story.append(KeepTogether([
        _section_title('Calibration Readings', styles),
        Spacer(1, 2*mm),
        _readings_table(session, styles, cmc_enabled, cmc_points),
    ]))
    story.append(Spacer(1, 4*mm))
    story.append(_summary_table(session, styles))
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(_signatures(session, styles))

    doc.build(story)
    return output_path


# ── section builders ──────────────────────────────────────────────────

def _header(session: CalibrationSession, styles) -> Table:
    logo_style = ParagraphStyle('lg', fontSize=20, fontName='Helvetica-Bold',
                                textColor=ACCENT)
    title_style = ParagraphStyle('tt', fontSize=15, fontName='Helvetica-Bold',
                                 textColor=NAVY, leading=19)
    sub_style   = ParagraphStyle('ts', fontSize=9, textColor=GREY, leading=13)

    data = [[
        Paragraph('TIPL', logo_style),
        [Paragraph('Calibration Certificate', title_style),
         Paragraph('Dry Block Temperature Calibrator  ·  TIPL Calibration Laboratory', sub_style)],
    ]]
    t = Table(data, colWidths=[26*mm, None])
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    return t


def _meta_table(session: CalibrationSession, styles) -> Table:
    lbl = ParagraphStyle('ml', fontSize=8, textColor=GREY)
    val = ParagraphStyle('mv', fontSize=10, fontName='Helvetica-Bold', textColor=NAVY)
    mono = ParagraphStyle('mm', fontSize=10, fontName='Courier-Bold', textColor=NAVY)

    rows = [
        [Paragraph('Certificate No', lbl),
         Paragraph(session.cert_no, mono),
         Paragraph('Date / Time', lbl),
         Paragraph(f'{session.date.isoformat()}  ·  {session.time_str}', mono)],
        [Paragraph('Customer', lbl),
         Paragraph(session.customer, val),
         Paragraph('Address', lbl),
         Paragraph(session.address or '—', val)],
    ]
    t = Table(rows, colWidths=[26*mm, 72*mm, 22*mm, None])
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND',    (0,0), (-1,-1), LIGHT),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), 4),
        ('BOX',           (0,0), (-1,-1), 0.4, BORDER),
    ]))
    return t


def _instrument_table(session: CalibrationSession, styles) -> Table:
    """Two-column layout: Master RTD on left, UUT on right."""
    hdr  = ParagraphStyle('ih', fontSize=9, fontName='Helvetica-Bold', textColor=colors.white)
    lbl  = ParagraphStyle('il', fontSize=8, textColor=GREY)
    val  = ParagraphStyle('iv', fontSize=9, fontName='Helvetica-Bold', textColor=NAVY)

    def _col(title: str, info: InstrumentInfo, color, extra_lbl: str, extra_val: str):
        rows = [
            [Paragraph(title, hdr)],
            [_pair(lbl, val, 'Instrument Type', info.instrument_type)],
            [_pair(lbl, val, 'Make',            info.make)],
            [_pair(lbl, val, 'Model',           info.model)],
            [_pair(lbl, val, 'Serial No',       info.serial_no)],
            [_pair(lbl, val, extra_lbl,         extra_val)],
        ]
        t = Table(rows, colWidths=[None])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (0,0), color),
            ('BACKGROUND',    (0,1), (0,-1), LIGHT),
            ('BOX',           (0,0), (-1,-1), 0.4, BORDER),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, BORDER),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 7),
        ]))
        return t

    master_tbl = _col('Master RTD — Standard Reference Sensor',
                       session.master_info, ACCENT,
                       'Certificate No', session.master_info.cert_number)
    uut_tbl    = _col('UUT — Unit Under Test',
                       session.uut_info, AMBER,
                       'Tag Number', session.uut_info.tag_number)

    outer = Table([[master_tbl, uut_tbl]], colWidths=['50%', '50%'])
    outer.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('INNERGRID',    (0,0), (-1,-1), 4, colors.white),
    ]))
    return outer


def _pair(lbl_style, val_style, label: str, value: str) -> Table:
    """Key-value pair inside an instrument card."""
    t = Table(
        [[Paragraph(label, lbl_style), Paragraph(value or '—', val_style)]],
        colWidths=[28*mm, None]
    )
    t.setStyle(TableStyle([
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 0),
    ]))
    return t


def _readings_table(session: CalibrationSession, styles, cmc_enabled: bool, cmc_points: list) -> Table:
    hdr_s = ParagraphStyle('rh', fontSize=8, fontName='Helvetica-Bold',
                           textColor=colors.white, alignment=TA_CENTER)
    cel_s = ParagraphStyle('rc', fontSize=9, fontName='Courier', alignment=TA_CENTER)
    res_s = ParagraphStyle('rr', fontSize=9, fontName='Helvetica-Bold', alignment=TA_CENTER)

    headers = ['#', 'Setpoint\n°C', 'Master RTD\n°C', 'UUT\n°C', 'Error\n°C']
    col_w   = [9*mm, 22*mm, 28*mm, 22*mm, 23*mm]
    if cmc_enabled:
        headers.append('CMC')
        col_w.append(20*mm)

    data = [[Paragraph(h, hdr_s) for h in headers]]

    for i, pt in enumerate(session.points):
        err  = pt.error
        sign = '+' if err >= 0 else ''
        err_color = '#ef4444' if abs(err) > 1 else '#1a2332'
        row = [
            Paragraph(str(i+1), cel_s),
            Paragraph(f'{pt.setpoint:.1f}',   cel_s),
            Paragraph(f'{pt.master_rtd:.2f}', cel_s),
            Paragraph(f'{pt.uut:.2f}',        cel_s),
            Paragraph(f'<font color="{err_color}"><b>{sign}{err:.3f}</b></font>', res_s),
        ]
        if cmc_enabled:
            cmc_val = interpolate_cmc(cmc_points, pt.setpoint)
            row.append(Paragraph(f'{cmc_val:.3f}' if cmc_val is not None else '—', cel_s))
        data.append(row)

    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',     (0,0), (-1,0),  NAVY),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT]),
        ('GRID',           (0,0), (-1,-1), 0.4, BORDER),
        ('VALIGN',         (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',     (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',  (0,0), (-1,-1), 5),
    ]))
    return t


def _summary_table(session: CalibrationSession, styles) -> Table:
    n = len(session.points)

    lbl_s = ParagraphStyle('sl', fontSize=8, textColor=GREY, alignment=TA_CENTER)
    val_s = ParagraphStyle('sv', fontSize=14, fontName='Helvetica-Bold', alignment=TA_CENTER)

    row = [[Paragraph('Points', lbl_s), Paragraph(str(n), val_s)]]
    t = Table(row, colWidths=[None])
    t.setStyle(TableStyle([
        ('BOX',        (0,0), (-1,-1), 0.5, BORDER),
        ('BACKGROUND', (0,0), (-1,-1), LIGHT),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING',(0,0),(-1,-1), 8),
    ]))
    return t


def _signatures(session: CalibrationSession, styles) -> Table:
    lbl_s = ParagraphStyle('sigl', fontSize=8, textColor=GREY)
    val_s = ParagraphStyle('sigv', fontSize=10, fontName='Helvetica-Bold', textColor=NAVY)
    data = [[
        [Paragraph(session.performed_by, val_s), Paragraph('Test Performed By', lbl_s)],
        '',
        [Paragraph(session.verified_by,  val_s), Paragraph('Verified By', lbl_s)],
    ]]
    t = Table(data, colWidths=[None, 30*mm, None])
    t.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    return t


def _section_title(text: str, styles) -> Paragraph:
    return Paragraph(text.upper(), ParagraphStyle(
        'sec', fontSize=8, fontName='Helvetica-Bold',
        textColor=GREY, letterSpacing=0.8,
    ))
