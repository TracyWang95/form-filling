'use client';

import { FormField } from '@/types';

interface FormFieldsProps {
  fields: FormField[];
}

// 常见表单字段的中文翻译映射
const labelTranslations: Record<string, string> = {
  // W-9 表单字段
  'Name of entity/individual': '实体/个人名称',
  'Business name/disregarded entity name': '企业名称/被忽略实体名称',
  'Individual/sole proprietor checkbox': '个人/独资经营者',
  'C corporation checkbox': 'C 型公司',
  'S corporation checkbox': 'S 型公司',
  'Partnership checkbox': '合伙企业',
  'Trust/estate checkbox': '信托/遗产',
  'LLC checkbox': '有限责任公司 (LLC)',
  'LLC tax classification code': 'LLC 税务分类代码',
  'Other (see instructions) checkbox': '其他（见说明）',
  'Partnership/Trust/estate/LLC-P details': '合伙/信托/遗产/LLC-P 详情',
  'Outside the United States checkbox': '美国境外',
  'Exempt payee code': '豁免收款人代码',
  'Exempt payee code (if any)': '豁免收款人代码（如有）',
  'FATCA exemption code': 'FATCA 豁免代码',
  'Exemption from FATCA reporting code': 'FATCA 申报豁免代码',
  'Exemption from Foreign Account Tax Compliance Act (FATCA) reporting code (if any)': 'FATCA 申报豁免代码（如有）',
  'Address (number, street, apt/suite)': '地址（门牌号、街道、公寓/套房）',
  'City, state, and ZIP code': '城市、州和邮编',
  "Requester's name and address": '申请人姓名和地址',
  'Account number(s) (optional)': '账户号码（可选）',
  'SSN Part 1 (3 digits)': '社会安全号 第1部分（3位）',
  'SSN Part 2 (2 digits)': '社会安全号 第2部分（2位）',
  'SSN Part 3 (4 digits)': '社会安全号 第3部分（4位）',
  'EIN Part 1 (2 digits)': '雇主识别号 第1部分（2位）',
  'EIN Part 2 (7 digits)': '雇主识别号 第2部分（7位）',
  // 通用字段
  'Name': '姓名',
  'Address': '地址',
  'City': '城市',
  'State': '州/省',
  'ZIP': '邮编',
  'Phone': '电话',
  'Email': '电子邮箱',
  'Date': '日期',
  'Signature': '签名',
};

// 翻译字段标签
function translateLabel(label: string): string {
  // 精确匹配
  if (labelTranslations[label]) {
    return labelTranslations[label];
  }
  // 模糊匹配（包含关键词）
  for (const [eng, chn] of Object.entries(labelTranslations)) {
    if (label.toLowerCase().includes(eng.toLowerCase())) {
      return chn;
    }
  }
  return label;
}

function FieldTypeIcon({ type }: { type: FormField['field_type'] }) {
  const iconClass = "w-3.5 h-3.5";

  switch (type) {
    case 'text':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
        </svg>
      );
    case 'checkbox':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
    case 'dropdown':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      );
    case 'radio':
      return (
        <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="12" r="9" strokeWidth={2} />
          <circle cx="12" cy="12" r="4" fill="currentColor" />
        </svg>
      );
  }
}

const typeLabels: Record<string, string> = {
  'text': '文本',
  'checkbox': '复选框',
  'dropdown': '下拉选项',
  'radio': '单选',
};

export default function FormFields({ fields }: FormFieldsProps) {
  if (fields.length === 0) {
    return (
      <div className="text-center py-8 text-foreground-muted">
        <p>未检测到表单字段</p>
        <p className="text-sm mt-1">请上传包含可填写字段的 PDF</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground-secondary">
          检测到的字段
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-foreground/10 text-foreground">
          {fields.length} 个字段
        </span>
      </div>

      <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-2">
        {fields.map((field, index) => {
          const label = field.friendly_label || field.label_context || '未命名字段';
          const translatedLabel = translateLabel(label);
          
          return (
            <div
              key={`${field.field_id}-${index}`}
              className="px-3 py-2 rounded-lg bg-background-tertiary border border-border hover:bg-foreground/5 transition-colors"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <span className="flex items-center justify-center w-5 h-5 rounded bg-background-secondary text-foreground-muted flex-shrink-0">
                    <FieldTypeIcon type={field.field_type} />
                  </span>
                  <span className="text-sm text-foreground truncate">
                    {translatedLabel}
                  </span>
                </div>
                <span className="text-xs px-1.5 py-0.5 rounded bg-background-secondary text-foreground-muted flex-shrink-0">
                  {typeLabels[field.field_type] || field.field_type}
                </span>
              </div>

              {field.current_value && field.current_value !== 'Off' && (
                <div className="mt-1 ml-7 text-xs text-success">
                  ✓ {field.current_value === 'Yes' || field.current_value === 'On' ? '已勾选' : field.current_value}
                </div>
              )}

              {field.options && field.options.length > 0 && (
                <div className="mt-1 ml-7 flex flex-wrap gap-1">
                  {field.options.slice(0, 3).map((opt) => (
                    <span key={opt} className="text-xs px-1.5 py-0.5 rounded bg-background-secondary text-foreground-muted">
                      {opt}
                    </span>
                  ))}
                  {field.options.length > 3 && (
                    <span className="text-xs text-foreground-muted">
                      +{field.options.length - 3}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
