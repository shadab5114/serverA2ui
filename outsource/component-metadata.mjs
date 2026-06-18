/**
 * Single source of truth describing every public @pds/core component and its
 * props. Consumed by `generate-catalog.mjs` to emit:
 *   - `catalog.json`  (A2UI catalog format)
 *   - `schemas.js`/`schemas.d.ts`  (zod schemas, one per component)
 *
 * Prop `type` values: 'string' | 'number' | 'boolean' | 'enum' | 'node'
 *                     | 'object' | 'array'.
 */

const SURFACE = [
    'lightPrimary',
    'lightSecondary',
    'lightBrandNeutral',
    'darkPrimary',
    'darkSecondary',
    'darkBrandHighlight',
];

const DROP_SHADOW = ['none', 'subtle', 'moderate'];
const BADGE_COLORS = [
    'red',
    'yellow',
    'green',
    'orange',
    'blue',
    'neonYellow',
    'grayHighContrast',
    'grayLowContrast',
    'black',
    'white',
];
const PRIMITIVES = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'p'];
const LOCKUP_TITLE_SIZES = [
    'bodySmall',
    'bodyMedium',
    'bodyLarge',
    'titleSmall',
    'titleXSmall',
    'title2XSmall',
    'titleMedium',
    'titleLarge',
    'titleXLarge',
    'title2XLarge',
    'featureSmall',
    'featureMedium',
];
const LOCKUP_SUB_SIZES = [
    'bodySmall',
    'bodyMedium',
    'bodyLarge',
    'titleSmall',
    'titleXSmall',
    'titleMedium',
];

const surfaceProp = {
    name: 'surface',
    type: 'enum',
    enum: SURFACE,
    default: 'lightPrimary',
    description: 'The surface the component is placed on; drives token colours.',
};

/** @type {Array<{name:string,description:string,props:Array<object>}>} */
export const components = [
    {
        name: 'Button',
        description: 'A call-to-action button supporting primary/secondary styles and surfaces.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Button label content.' },
            { name: 'kind', type: 'enum', enum: ['primary', 'secondary'], default: 'primary', description: 'Visual style.' },
            { name: 'size', type: 'enum', enum: ['small', 'large'], default: 'large', description: 'Button size.' },
            surfaceProp,
            { name: 'width', type: 'string', default: 'auto', description: 'Fixed width as a CSS value.' },
            { name: 'role', type: 'enum', enum: ['link', 'button'], default: 'button', description: 'Accessibility role.' },
            { name: 'href', type: 'string', description: 'Renders the button as an anchor when set.' },
            { name: 'disabled', type: 'boolean', default: false, description: 'Disables the button.' },
            { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
        ],
    },
    {
        name: 'TextLink',
        description: 'An inline or standalone text hyperlink.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Link text.' },
            { name: 'kind', type: 'enum', enum: ['inline', 'standalone'], default: 'inline', description: 'Inline (underlined) or standalone (bold) link.' },
            { name: 'size', type: 'enum', enum: ['large', 'small'], default: 'large', description: 'Link size.' },
            surfaceProp,
            { name: 'href', type: 'string', description: 'Destination URL.' },
            { name: 'disabled', type: 'boolean', description: 'Disables the link.' },
            { name: 'wrapText', type: 'boolean', description: 'Allow the text to wrap.' },
            { name: 'role', type: 'string', description: 'Accessibility role.' },
            { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
        ],
    },
    {
        name: 'TextLinkCaret',
        description: 'A text link with a leading or trailing caret icon.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Link text.' },
            { name: 'iconPosition', type: 'enum', enum: ['left', 'right'], default: 'right', description: 'Caret position.' },
            { name: 'kind', type: 'enum', enum: ['inline', 'standalone'], default: 'standalone', description: 'Link style.' },
            { name: 'size', type: 'enum', enum: ['large', 'small'], default: 'large', description: 'Link size.' },
            surfaceProp,
            { name: 'href', type: 'string', description: 'Destination URL.' },
            { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
        ],
    },
    {
        name: 'ButtonGroup',
        description: 'Lays out a set of buttons / links with shared alignment and sizing.',
        props: [
            { name: 'items', type: 'array', of: { sharedRef: 'ButtonGroupItem' }, required: true, description: 'The buttons/links to render (discriminated by `kind`).' },
            { name: 'alignment', type: 'enum', enum: ['left', 'center', 'right'], default: 'center', description: 'Horizontal alignment.' },
            { name: 'buttonWidth', type: 'string', default: 'auto', description: 'Fixed width applied to each button.' },
            { name: 'rowQuantity', type: 'number', description: 'Number of items per row.' },
            { name: 'size', type: 'enum', enum: ['large', 'small'], default: 'large', description: 'Size applied to all items.' },
            surfaceProp,
            { name: 'width', type: 'string', description: 'Width of the group container.' },
        ],
    },
    {
        name: 'Text',
        description: 'Typographic text supporting body, title and feature scales.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Text content.' },
            { name: 'kind', type: 'enum', enum: ['body', 'title', 'feature'], default: 'body', description: 'Typography scale.' },
            { name: 'size', type: 'enum', enum: ['2xsmall', 'xsmall', 'small', 'medium', 'large', 'xlarge', '2xlarge'], description: 'Size within the scale (availability varies by kind).' },
            { name: 'bold', type: 'boolean', default: false, description: 'Render at bold weight.' },
            { name: 'color', type: 'string', description: 'Text colour.' },
            { name: 'primitive', type: 'enum', enum: PRIMITIVES, default: 'p', description: 'HTML element used to render the text.' },
        ],
    },
    {
        name: 'Caret',
        description: 'A chevron/caret icon that inherits the surrounding text colour.',
        props: [
            { name: 'direction', type: 'enum', enum: ['left', 'right'], default: 'right', description: 'Chevron direction.' },
            { name: 'size', type: 'number', default: 12, description: 'Square size in pixels.' },
        ],
    },
    {
        name: 'DirectionalIcon',
        description: 'A trailing affordance icon: right-arrow or external-link.',
        props: [
            { name: 'name', type: 'enum', enum: ['right-arrow', 'external-link'], default: 'right-arrow', description: 'Glyph to render.' },
            { name: 'size', type: 'string', default: '20', description: 'Icon size (px number or CSS size).' },
            { name: 'color', type: 'string', description: 'Icon colour.' },
        ],
    },
    {
        name: 'Tooltip',
        description: 'A small, accessible info tooltip revealed on hover/focus.',
        props: [
            { name: 'title', type: 'string', description: 'Plain-text tooltip content.' },
            { name: 'children', type: 'node', description: 'Rich tooltip content (takes precedence over title).' },
            surfaceProp,
            { name: 'ariaLabel', type: 'string', default: 'More information', description: 'Accessible label for the trigger.' },
        ],
    },
    {
        name: 'Badge',
        description: 'A small label/pill, optionally with a tooltip.',
        props: [
            { name: 'children', type: 'node', description: 'Badge content.' },
            { name: 'backgroundColor', type: 'enum', enum: BADGE_COLORS, default: 'red', description: 'Predefined colour token (or any CSS colour).' },
            surfaceProp,
            { name: 'elementColor', type: 'string', description: 'Overrides the text colour.' },
            { name: 'numberOfLines', type: 'number', default: 1, description: 'Clamp the content to N lines.' },
            { name: 'maxWidth', type: 'string', default: 'auto', description: 'Maximum width as a CSS value.' },
            { name: 'padding', type: 'string', description: 'Custom CSS padding.' },
            { name: 'borderRadius', type: 'string', description: 'Custom CSS border radius.' },
            { name: 'tooltip', type: 'object', ref: 'Tooltip', description: 'Tooltip configuration.' },
        ],
    },
    {
        name: 'BadgeIndicator',
        description: 'A dot (simple) or numbered notification indicator.',
        props: [
            { name: 'kind', type: 'enum', enum: ['simple', 'numbered'], default: 'simple', description: 'Dot or numbered indicator.' },
            surfaceProp,
            { name: 'showBorder', type: 'boolean', default: true, description: 'Shows a border ring around the container.' },
            { name: 'showDot', type: 'boolean', default: true, description: 'Shows the dot when kind is simple.' },
            { name: 'backgroundColor', type: 'string', default: 'red', description: 'Colour token or custom CSS colour.' },
            { name: 'maximumDigits', type: 'enum', enum: [1, 2, 3, 4, 5, 6, 'none'], default: 2, description: 'Max digits before truncating with "+".' },
            { name: 'leadingCharacter', type: 'string', description: 'Character shown before the number.' },
            { name: 'trailingText', type: 'string', description: 'Text shown after the number.' },
            { name: 'size', type: 'enum', enum: ['small', 'medium', 'large', 'xlarge', '2xlarge'], default: 'small', description: 'Font size for numbered content.' },
            { name: 'containerSize', type: 'string', default: '16px', description: 'Container height/min-width.' },
            { name: 'decimalPoints', type: 'number', default: 0, description: 'Decimal places retained for floats.' },
            { name: 'elementColor', type: 'string', description: 'Text/dot colour override.' },
            { name: 'borderColor', type: 'string', description: 'Border colour override.' },
            { name: 'padding', type: 'string', description: 'Custom padding for numbered content.' },
            { name: 'dotSize', type: 'string', default: '6px', description: 'Dot size when kind is simple.' },
            { name: 'children', type: 'string', description: 'Numbered content. Defaults to "0".' },
            { name: 'ariaHidden', type: 'boolean', description: 'Hides content from assistive tech.' },
        ],
    },
    {
        name: 'Image',
        description: 'A token-aware image wrapper with sizing, radius and border.',
        props: [
            { name: 'src', type: 'string', required: true, description: 'Image source URL.' },
            { name: 'alt', type: 'string', description: 'Alternative text.' },
            { name: 'width', type: 'string', description: 'CSS width.' },
            { name: 'height', type: 'string', description: 'CSS height.' },
            { name: 'borderRadius', type: 'string', description: 'Corner radius.' },
            { name: 'showBorder', type: 'boolean', description: 'Draws a low-contrast border.' },
            { name: 'objectFit', type: 'string', default: 'cover', description: 'CSS object-fit behaviour.' },
        ],
    },
    {
        name: 'TileContainer',
        description: 'A surface container for grouping content; interactive when href/onClick is set.',
        props: [
            { name: 'children', type: 'node', description: 'Tile content.' },
            { name: 'background', type: 'string', default: 'lightSecondary', description: 'Surface token, image URL, or CSS colour.' },
            surfaceProp,
            { name: 'padding', type: 'string', default: '4X', description: 'Inside padding (space token or CSS value).' },
            { name: 'showBorder', type: 'boolean', description: 'Draws a border around the tile.' },
            { name: 'dropShadow', type: 'enum', enum: DROP_SHADOW, default: 'none', description: 'Drop shadow elevation.' },
            { name: 'borderRadius', type: 'string', default: 'standard', description: 'Corner radius preset or CSS value.' },
            { name: 'aspectRatio', type: 'string', default: '1/1', description: 'Aspect ratio when height is not set.' },
            { name: 'height', type: 'string', description: 'Fixed height (CSS value).' },
            { name: 'width', type: 'string', default: '100%', description: 'Fixed width (CSS value).' },
            { name: 'imageFallbackColor', type: 'string', description: 'Fallback colour for image backgrounds.' },
            { name: 'elementSurface', type: 'string', description: 'Surface context for child colours on custom backgrounds.' },
            { name: 'focusBorderPosition', type: 'enum', enum: ['inside', 'outside'], default: 'outside', description: 'Focus-ring position.' },
            { name: 'href', type: 'string', description: 'Makes the tile a link.' },
            { name: 'role', type: 'string', description: 'Accessibility role.' },
            { name: 'target', type: 'string', description: 'Link target.' },
            { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
        ],
    },
    {
        name: 'TitleLockup',
        description: 'Composes eyebrow, title and subtitle with responsive size cascade.',
        props: [
            { name: 'eyebrow', type: 'object', ref: 'TitleLockupEyebrow', description: 'Eyebrow config (TitleLockupEyebrow props).' },
            { name: 'title', type: 'object', ref: 'TitleLockupTitle', description: 'Title config (TitleLockupTitle props).' },
            { name: 'subtitle', type: 'object', ref: 'TitleLockupSubtitle', description: 'Subtitle config (TitleLockupSubtitle props).' },
            { name: 'children', type: 'node', description: 'Declarative children when not using object props.' },
            { name: 'textAlignment', type: 'enum', enum: ['left', 'center'], default: 'left', description: 'Horizontal text alignment.' },
            surfaceProp,
            { name: 'viewport', type: 'enum', enum: ['mobile', 'tablet', 'desktop'], description: 'Force a viewport for responsive sizing.' },
            { name: 'viewportOverride', type: 'object', description: 'Per-viewport prop overrides.' },
        ],
    },
    {
        name: 'TitleLockupTitle',
        description: 'The title element of a TitleLockup.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Title text.' },
            { name: 'size', type: 'enum', enum: LOCKUP_TITLE_SIZES, description: 'Font size token.' },
            { name: 'primitive', type: 'enum', enum: PRIMITIVES, default: 'h1', description: 'HTML element.' },
            { name: 'bold', type: 'boolean', description: 'Render at bold weight.' },
            surfaceProp,
            { name: 'color', type: 'string', description: 'Text colour override.' },
            { name: 'numberOfLines', type: 'number', description: 'Clamp to N lines.' },
            { name: 'isStandAlone', type: 'boolean', description: 'Disables the bottom margin when there is no subtitle.' },
            { name: 'tooltip', type: 'object', ref: 'Tooltip', description: 'Tooltip configuration.' },
        ],
    },
    {
        name: 'TitleLockupSubtitle',
        description: 'The subtitle element of a TitleLockup.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Subtitle text.' },
            { name: 'size', type: 'enum', enum: LOCKUP_SUB_SIZES, description: 'Font size token.' },
            { name: 'primitive', type: 'enum', enum: PRIMITIVES, default: 'h2', description: 'HTML element.' },
            { name: 'bold', type: 'boolean', description: 'Render at bold weight.' },
            surfaceProp,
            { name: 'color', type: 'string', description: 'Text colour override.' },
            { name: 'numberOfLines', type: 'number', description: 'Clamp to N lines.' },
            { name: 'tooltip', type: 'object', ref: 'Tooltip', description: 'Tooltip configuration.' },
        ],
    },
    {
        name: 'TitleLockupEyebrow',
        description: 'The eyebrow element of a TitleLockup.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Eyebrow text.' },
            { name: 'size', type: 'enum', enum: LOCKUP_SUB_SIZES, description: 'Font size token.' },
            { name: 'primitive', type: 'enum', enum: PRIMITIVES, default: 'h3', description: 'HTML element.' },
            { name: 'bold', type: 'boolean', description: 'Render at bold weight.' },
            surfaceProp,
            { name: 'color', type: 'string', description: 'Text colour override.' },
            { name: 'numberOfLines', type: 'number', description: 'Clamp to N lines.' },
            { name: 'isStandAlone', type: 'boolean', description: 'Disables paddingBottom when standalone.' },
            { name: 'paddingBottom', type: 'string', description: 'Space rendered beneath the eyebrow.' },
            { name: 'tooltip', type: 'object', ref: 'Tooltip', description: 'Tooltip configuration.' },
        ],
    },
    {
        name: 'ScreenReaderText',
        description: 'Text hidden visually but announced by screen readers.',
        props: [
            { name: 'children', type: 'node', required: true, description: 'Screen-reader-only content.' },
        ],
    },
    {
        name: 'Tilelet',
        description: 'A content tile composed from TileContainer, TitleLockup, Badge and Image.',
        props: [
            { name: 'title', type: 'object', ref: 'TitleLockupTitle', description: 'Title config (TitleLockupTitle props).' },
            { name: 'subtitle', type: 'object', ref: 'TitleLockupSubtitle', description: 'Subtitle config.' },
            { name: 'eyebrow', type: 'object', ref: 'TitleLockupEyebrow', description: 'Eyebrow config.' },
            { name: 'badge', type: 'object', ref: 'Badge', description: 'Badge config shown at the top.' },
            { name: 'image', type: 'object', ref: 'Image', description: 'Image config.' },
            { name: 'imagePosition', type: 'enum', enum: ['belowText', 'aboveText'], default: 'belowText', description: 'Image vertical position relative to text.' },
            { name: 'imageAlignment', type: 'enum', enum: ['center', 'left', 'right'], default: 'center', description: 'Image horizontal alignment.' },
            { name: 'directionalIcon', type: 'object', ref: 'DirectionalIcon', description: 'Trailing directional icon config.' },
            { name: 'renderDescriptiveIcon', type: 'boolean', default: false, description: 'Exposes the directional icon to assistive tech.' },
            { name: 'iconMarginTop', type: 'string', default: '16px', description: 'Top margin for the icon container.' },
            { name: 'textAlignment', type: 'enum', enum: ['center', 'left'], default: 'left', description: 'Horizontal text alignment.' },
            { name: 'textPosition', type: 'enum', enum: ['top', 'middle', 'bottom'], default: 'top', description: 'Vertical text placement.' },
            { name: 'textWidth', type: 'string', default: '100%', description: 'Width of the text content area.' },
            { name: 'padding', type: 'string', default: '4X', description: 'Inside padding.' },
            { name: 'background', type: 'string', default: 'lightSecondary', description: 'Surface token, image URL, or CSS colour.' },
            surfaceProp,
            { name: 'elementSurface', type: 'string', description: 'Surface context for child colours.' },
            { name: 'showBorder', type: 'boolean', description: 'Draws an adaptive border.' },
            { name: 'dropShadow', type: 'enum', enum: DROP_SHADOW, default: 'none', description: 'Drop shadow elevation.' },
            { name: 'borderRadius', type: 'string', default: 'standard', description: 'Corner radius preset or CSS value.' },
            { name: 'aspectRatio', type: 'string', default: 'none', description: 'Aspect ratio (content-driven by default).' },
            { name: 'imageFallbackColor', type: 'string', description: 'Fallback colour for image backgrounds.' },
            { name: 'focusBorderPosition', type: 'enum', enum: ['inside', 'outside'], default: 'outside', description: 'Focus-ring position.' },
            { name: 'height', type: 'string', description: 'Fixed height.' },
            { name: 'width', type: 'string', default: '100%', description: 'Fixed width.' },
            { name: 'href', type: 'string', description: 'Makes the tilelet a link.' },
            { name: 'target', type: 'string', description: 'Link target.' },
            { name: 'role', type: 'enum', enum: ['button', 'link'], description: 'Semantic role.' },
            { name: 'ariaLabel', type: 'string', description: 'Accessible label (auto-generated when omitted).' },
        ],
    },
];

/**
 * Reusable shapes referenced by props via `sharedRef`. Each emits a `$defs`
 * entry in the catalog and a `<name>Schema` in schemas.js. A `oneOf` shape is
 * a discriminated union of variants.
 * @type {Array<{name:string,description?:string,oneOf?:Array<{props:Array<object>}>,props?:Array<object>}>}
 */
export const sharedDefs = [
    {
        name: 'ButtonGroupItem',
        description:
            'A single entry in ButtonGroup.items, discriminated by `kind`: primary/secondary render a Button, textLink a TextLink, textLinkCaret a TextLinkCaret.',
        oneOf: [
            {
                props: [
                    { name: 'kind', type: 'enum', enum: ['primary', 'secondary'], required: true, description: 'Renders a Button of this kind.' },
                    { name: 'children', type: 'node', required: true, description: 'Button label.' },
                    { name: 'href', type: 'string', description: 'Renders the button as a link when set.' },
                    { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
                ],
            },
            {
                props: [
                    { name: 'kind', type: 'enum', enum: ['textLink'], required: true, description: 'Renders a TextLink.' },
                    { name: 'children', type: 'node', required: true, description: 'Link text.' },
                    { name: 'href', type: 'string', description: 'Destination URL.' },
                    { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
                ],
            },
            {
                props: [
                    { name: 'kind', type: 'enum', enum: ['textLinkCaret'], required: true, description: 'Renders a TextLinkCaret.' },
                    { name: 'children', type: 'node', required: true, description: 'Link text.' },
                    { name: 'href', type: 'string', description: 'Destination URL.' },
                    { name: 'iconPosition', type: 'enum', enum: ['left', 'right'], default: 'right', description: 'Caret position.' },
                    { name: 'ariaLabel', type: 'string', description: 'Accessible label.' },
                ],
            },
        ],
    },
];

export const catalogMeta = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: 'https://pdesign.dev/catalog/v1/catalog.json',
    title: 'PDS Core Catalog',
    description: 'A2UI-style catalog of @pds/core (pdesign-ui) components.',
    catalogId: 'https://pdesign.dev/catalog/v1/catalog.json',
};
