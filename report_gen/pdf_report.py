import sys
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether, Image, Flowable
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


class FullBleedHR(Flowable):
    """
    A horizontal rule that reaches the true physical page edges, not just
    the content frame between the margins. A normal HRFlowable(width='100%')
    is clipped to the frame's width, so it stops short of the page edge by
    exactly the margin — this overshoots by the margin size on each side
    instead, while still flowing at whatever vertical position the
    surrounding content puts it (unlike the fixed-position footer chrome).
    """
    def __init__(self, content_width: float, left_margin: float, right_margin: float,
                 thickness: float = 0.75, color=colors.black):
        super().__init__()
        self.width = content_width
        self.height = thickness
        self._left_margin = left_margin
        self._right_margin = right_margin
        self._thickness = thickness
        self._color = color

    def draw(self) -> None:
        self.canv.saveState()
        self.canv.setStrokeColor(self._color)
        self.canv.setLineWidth(self._thickness)
        self.canv.line(-self._left_margin, 0, self.width + self._right_margin, 0)
        self.canv.restoreState()


def _tipl_logo_path() -> Path:
    """
    TIPL's own logo — bundled read-only with the app (asset/logo.png), not
    something a lab using this software can change. Printed in the
    certificate footer alongside the fixed "developed and maintained by"
    credit, same resolution pattern as main.py's _icon_path(): bundled
    resources live under sys._MEIPASS when frozen (PyInstaller --onefile),
    unlike writable per-lab data (see db/settings_store.py's _app_root()).
    """
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / 'asset' / 'logo.png'


def generate_pdf(session: CalibrationSession, output_path: Path) -> Path:
    """
    Render a full calibration certificate PDF including instrument details.
    Returns the output path on success.
    """
    settings = SettingsStore().load()
    cmc_enabled = bool(settings.get('cmc_enabled'))
    cmc_points  = settings.get('cmc_points', [])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    left_margin, right_margin = 16*mm, 16*mm
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=left_margin, rightMargin=right_margin,
        # Extra bottom margin — the fixed TIPL footer (_draw_footer) is
        # drawn directly on the canvas below the normal content flow, so
        # the flowables need to stop well short of it on every page.
        topMargin=14*mm,  bottomMargin=26*mm,
    )
    styles = getSampleStyleSheet()
    story  = []

    story.append(_header(settings))
    story.append(Spacer(1, 4*mm))
    story.append(FullBleedHR(doc.width, left_margin, right_margin))
    story.append(Spacer(1, 3*mm))
    story.append(_customer_table(session, styles))
    story.append(Spacer(1, 4*mm))
    story.append(_reference_table(session, styles, settings))
    story.append(Spacer(1, 4*mm))
    story.append(_instrument_table(session, styles))
    story.append(Spacer(1, 4*mm))
    story.append(KeepTogether([
        _section_title('Calibration Readings', styles),
        Spacer(1, 2*mm),
        _readings_table(session, styles, cmc_enabled, cmc_points),
    ]))
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDER))
    story.append(Spacer(1, 18*mm))
    story.append(_signatures(session, styles))

    # Fixed TIPL credit — drawn on every page's canvas rather than added
    # as a flowable, so it always sits at the true bottom margin instead
    # of wherever the content happens to end. Not lab-configurable (see
    # _draw_footer) — the lab's own branding is in _header() instead.
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return output_path


# ── section builders ──────────────────────────────────────────────────

def _header(settings: dict) -> Table:
    """
    Lab branding — logo, company name, company address — all from the
    operating lab's own Settings (user_profile), not TIPL's. This is what
    changes from lab to lab when this software is deployed elsewhere;
    TIPL's own credit is fixed and lives only in the footer (_draw_footer).
    """
    profile = settings.get('user_profile', {})
    company_name    = profile.get('company_name', '') or '—'
    company_address = profile.get('company_address', '') or ''
    logo_path        = profile.get('logo_path')

    name_style  = ParagraphStyle('cn', fontSize=14, fontName='Helvetica-Bold',
                                 textColor=NAVY, leading=17)
    addr_style  = ParagraphStyle('ca', fontSize=8.5, textColor=GREY, leading=12)
    title_style = ParagraphStyle('tt', fontSize=15, fontName='Helvetica-Bold',
                                 textColor=NAVY, leading=19, alignment=TA_RIGHT)
    sub_style   = ParagraphStyle('ts', fontSize=9, textColor=GREY, leading=13,
                                 alignment=TA_RIGHT)

    logo_cell = ''
    if logo_path and Path(logo_path).exists():
        try:
            logo_cell = Image(logo_path, width=28*mm, height=14*mm)
        except Exception:
            logo_cell = ''

    company_block = [Paragraph(company_name, name_style)]
    if company_address:
        company_block.append(Paragraph(company_address.replace('\n', '<br/>'), addr_style))

    title_block = [
        Paragraph('Calibration Certificate', title_style),
    ]

    data = [[logo_cell, company_block, title_block]]
    # Logo column widened to 28mm to match the Image's own width above —
    # it was previously 26mm, 2mm narrower than the image, so the logo
    # overflowed into what should have been the gap before company_block.
    t = Table(data, colWidths=[30*mm, None, 90*mm])
    t.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        # >=10px (~3.5mm) gap between the logo and the company name/address.
        ('RIGHTPADDING', (0,0), (0,0),   4*mm),
    ]))
    return t


def _customer_table(session: CalibrationSession, styles) -> Table:
    """
    Customer/certificate identity grid — the first thing after the header,
    ahead of the reference-equipment block below it.
    """
    lbl  = ParagraphStyle('ml', fontSize=8, textColor=GREY)
    val  = ParagraphStyle('mv', fontSize=10, fontName='Helvetica-Bold', textColor=NAVY)
    mono = ParagraphStyle('mm', fontSize=10, fontName='Courier-Bold', textColor=NAVY)

    rows = [
        [Paragraph('Customer', lbl),
         Paragraph(session.customer, val),
         Paragraph('Certificate No', lbl),
         Paragraph(session.cert_no, mono)],
        [Paragraph('Address', lbl),
         Paragraph(session.address or '—', val),
         Paragraph('Date', lbl),
         Paragraph(session.date.strftime('%d-%m-%Y'), mono)],
    ]
    # 3rd column widened from 22mm to 28mm, same reason as _reference_table
    # below — "Certificate No" wrapped onto 2 lines in the narrower column.
    t = Table(rows, colWidths=[26*mm, 54*mm, 28*mm, None])
    t.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND',    (0,0), (-1,-1), LIGHT),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), 4),
        ('BOX',           (0,0), (-1,-1), 0.4, BORDER),
        ('LINEBELOW',     (0,0), (-1,0),  0.4, BORDER),
        ('LINEAFTER',     (1,0), (1,1),   0.4, BORDER),
    ]))
    return t


def _reference_table(session: CalibrationSession, styles, settings: dict) -> Table:
    """
    Reference equipment (the calibrator/dry-block's own traceability —
    Settings > Manufacturer) — its own heading band, above the
    model/serial and dry-block range detail rows, so it's clear at a
    glance which physical unit produced this certificate — see
    SetupScreen's Start validation, which requires these fields filled
    before a calibration can even begin.
    """
    lbl   = ParagraphStyle('ml', fontSize=8, textColor=GREY)
    val   = ParagraphStyle('mv', fontSize=10, fontName='Helvetica-Bold', textColor=NAVY)
    ref_s = ParagraphStyle('rs', fontSize=9, fontName='Helvetica-Bold',
                            textColor=colors.white, alignment=TA_CENTER)

    mfg = settings.get('manufacturer', {})
    rng = settings.get('calibrator_range', {})
    rmin, rmax = rng.get('min'), rng.get('max')

    ref_name = mfg.get('reference_equipment', '') or '—'
    heading = Paragraph(
        f'REFERENCE EQUIPMENT - &nbsp;&nbsp;&nbsp;{ref_name}',
        ref_s,
    )

    rows = [
        [heading, '', '', ''],
        [Paragraph('Model No', lbl),
         Paragraph(mfg.get('model_no', '') or '—', val),
         Paragraph('Serial No', lbl),
         Paragraph(mfg.get('serial_no', '') or '—', val)],
        [Paragraph('Range Minimum', lbl),
         Paragraph(f'{rmin:.0f} °C' if rmin is not None else '—', val),
         Paragraph('Range Maximum', lbl),
         Paragraph(f'{rmax:.0f} °C' if rmax is not None else '—', val)],
    ]
    # 3rd column widened from 22mm to 28mm — "Range Maximum" (and
    # "Serial No") wrapped onto 2 lines in the narrower column while the
    # 1st column's "Range Minimum"/"Model No" fit on 1, making that side
    # of the row look taller even though it's the same table row.
    t = Table(rows, colWidths=[26*mm, 54*mm, 28*mm, None])
    t.setStyle(TableStyle([
        ('SPAN',          (0,0), (3,0)),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('VALIGN',        (0,0), (3,0),  'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND',    (0,0), (-1,-1), LIGHT),
        ('BACKGROUND',    (0,0), (3,0),  ACCENT),
        ('ROUNDEDCORNERS',(0,0), (-1,-1), 4),
        ('BOX',           (0,0), (-1,-1), 0.4, BORDER),
        ('LINEBELOW',     (0,0), (-1,0),  0.4, BORDER),
        ('LINEBELOW',     (0,1), (-1,1),  0.4, BORDER),
        ('LINEAFTER',     (1,1), (1,2),   0.4, BORDER),
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

    master_tbl = _col('Standard Reference Sensor',
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

    headers = ['Sr no', 'Setpoint\n°C', 'Standard Reference Sensor\n°C', 'UUT\n°C', 'Error\n°C']
    # Widened to use the full page width (content area is ~178mm between
    # the 16mm margins) — narrower columns forced "Standard Reference
    # Sensor" to wrap across multiple lines and made the header row tall.
    col_w   = [14*mm, 34*mm, 54*mm, 34*mm, 40*mm]
    if cmc_enabled:
        headers.append('CMC')
        col_w = [12*mm, 30*mm, 48*mm, 28*mm, 32*mm, 24*mm]

    data = [[Paragraph(h, hdr_s) for h in headers]]

    for i, pt in enumerate(session.points):
        err  = pt.error
        sign = '+' if err >= 0 else ''
        err_color = '#1a2332'
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


# ── fixed footer — drawn on the canvas, not the flowable story ─────────

def _draw_footer(canvas, doc) -> None:
    """
    TIPL's own credit — logo, company name, and address — printed on
    every page at a fixed position near the bottom margin. This is the
    one piece of branding that stays the same no matter which lab is
    running the software; the lab's own identity is in _header() instead,
    built from that lab's Settings.
    """
    canvas.saveState()

    left_x    = doc.leftMargin
    right_x   = doc.pagesize[0] - doc.rightMargin
    rule_y    = 20*mm
    logo_w    = 30*mm
    logo_h    = 30*mm
    text_x    = left_x

    # Edge-to-edge, unlike the logo/text below which stay inside the
    # normal content margins — only the divider itself reaches the page
    # edges (0 to full page width), same full-bleed treatment as the
    # header's FullBleedHR.
    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(0.75)
    canvas.line(0, rule_y, doc.pagesize[0], rule_y)

    logo_path = _tipl_logo_path()
    if logo_path.exists():
        try:
            canvas.drawImage(
                str(logo_path), left_x, rule_y - 23*mm,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True, mask='auto',
            )
            text_x = left_x + logo_w + 1.5*mm
        except Exception:
            pass

    # Text block vertically centered against the logo (bottom at
    # rule_y-23mm, height logo_h, so center = rule_y - 23mm + logo_h/2),
    # same 3mm line spacing as before, just recentered as a block.
    text_center_y = rule_y - 23*mm + logo_h / 2

    canvas.setFont('Helvetica-Oblique', 7)
    canvas.setFillColor(GREY)
    canvas.drawString(text_x, text_center_y + 3*mm, 'Software developed and maintained by')

    canvas.setFont('Helvetica-Bold', 8)
    canvas.setFillColor(NAVY)
    canvas.drawString(text_x, text_center_y, 'Toshniwal Industries Private Limited')

    canvas.setFont('Helvetica', 7)
    canvas.drawString(text_x, text_center_y - 3*mm, 'Industrial estate, Makhupura, Ajmer - 305002')

    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(GREY)
    canvas.drawRightString(right_x, text_center_y, f'Page {doc.page}')

    canvas.restoreState()
