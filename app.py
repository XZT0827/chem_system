from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, session
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from database import init_database, get_connection
from import_data import import_excel_to_database
from formula_manager import (
    get_all_formulas, get_formulas_with_cost, get_today_lowest_cost_formulas,
    get_formulas_with_materials_for_display, get_formula_materials_with_prices
)
from export_data import (
    export_formula_list_to_excel, export_lowest_cost_to_excel,
    export_materials_detail_to_excel, export_materials_library_to_excel,
    export_customer_demands_to_excel
)
from material_customer_query import (
    get_all_materials, get_material_price_history, search_materials,
    get_daily_customer_demands, get_all_dates_with_data, get_customer_demand_statistics
)
from formula_optimizer import (
    init_optimizer_tables, get_all_material_groups, get_group_with_members,
    create_material_group, delete_material_group, add_member_to_group,
    remove_member_from_group, get_all_substitutions, add_substitution,
    delete_substitution, optimize_formula, save_optimized_formula,
    apply_optimized_formula, get_optimized_formula_history,
    get_all_materials_for_selection, get_quotation_formulas_for_optimization
)
from llm_service import (
    get_api_config, set_api_key, set_provider, LLM_CONFIG,
    ai_suggest_substitutions, ai_optimize_formula, ai_chat_assistant
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# 配置
UPLOAD_FOLDER = 'uploads'
EXPORT_FOLDER = 'exports'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# 创建必要的目录
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXPORT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['EXPORT_FOLDER'] = EXPORT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('没有选择文件', 'danger')
        return redirect(url_for('index'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('没有选择文件', 'danger')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        import_date = request.form.get('import_date', datetime.now().strftime('%Y-%m-%d'))
        result = import_excel_to_database(filepath, import_date)
        
        if result['success']:
            flash(result['message'], 'success')
            return redirect(url_for('formula_list'))
        else:
            flash(result['message'], 'danger')
            return redirect(url_for('index'))
    else:
        flash('文件格式不支持，请上传xlsx或xls文件', 'danger')
        return redirect(url_for('index'))

@app.route('/formulas')
def formula_list():
    search_keyword = request.args.get('search', '')
    formula_type = request.args.get('type', '')  # 确保默认值为空字符串而不是None
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    formulas = get_formulas_with_cost(target_date, search_keyword, formula_type)
    
    return render_template('formula_list.html',
                         formulas=formulas or [],
                         search_keyword=search_keyword,
                         formula_type=formula_type,  # 现在这里不会是None
                         target_date=target_date,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/lowest-cost-today')
def lowest_cost_today():
    """今日最低成本配方页面（可选择日期）"""
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    from formula_manager import get_lowest_cost_formulas_by_date
    results = get_lowest_cost_formulas_by_date(target_date)
    
    return render_template('lowest_cost_today.html',
                         results=results,
                         target_date=target_date,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/materials-detail')
def materials_detail():
    """配方原料横向明细页面（按产品编码查询，不需要日期）"""
    search_keyword = request.args.get('search', '')
    formula_type = request.args.get('type', '')
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    results = get_formulas_with_materials_for_display(target_date, search_keyword, formula_type)
    
    # 找出最多的原料数量
    max_materials = max((len(r['materials']) for r in results), default=0)
    
    return render_template('materials_detail_new.html',
                         results=results,
                         search_keyword=search_keyword,
                         formula_type=formula_type,
                         target_date=target_date,
                         max_materials=max_materials,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/export-formulas/<date>')
def export_formulas(date):
    """导出配方列表Excel"""
    filename = f"配方列表_{date}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_cost_summary_to_excel(date, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('formula_list'))

@app.route('/materials')
def materials_library():
    """原料库页面"""
    search_keyword = request.args.get('search', '')
    
    if search_keyword:
        materials = search_materials(search_keyword)
    else:
        materials = get_all_materials()
    
    return render_template('materials_library.html',
                         materials=materials,
                         search_keyword=search_keyword)

@app.route('/material/<material_code>')
def material_detail(material_code):
    """原料详情页面"""
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    prices = get_material_price_history(
        material_code,
        start_date if start_date else None,
        end_date if end_date else None
    )
    
    material_info = None
    if prices:
        material_info = {
            'code': prices[0]['material_code'],
            'name': prices[0]['material_name'],
            'model': prices[0]['material_model']
        }
    
    return render_template('material_detail.html',
                         material_info=material_info,
                         prices=prices,
                         start_date=start_date,
                         end_date=end_date,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/customer-demands')
def customer_demands():
    """每日客户需求页面"""
    date = request.args.get('date', '')
    
    if not date:
        all_dates = get_all_dates_with_data()
        date = all_dates[0] if all_dates else datetime.now().strftime('%Y-%m-%d')
    
    demands = get_daily_customer_demands(date)
    statistics = get_customer_demand_statistics(date)
    all_dates = get_all_dates_with_data()
    
    return render_template('customer_demands.html',
                         demands=demands,
                         statistics=statistics,
                         date=date,
                         all_dates=all_dates,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

# ========== 导出功能路由 ==========

@app.route('/export/formula-list')
def export_formula_list():
    """导出配方列表"""
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    search_keyword = request.args.get('search', '')
    formula_type = request.args.get('type', '')
    
    filename = f"配方列表_{target_date}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_formula_list_to_excel(target_date, search_keyword, formula_type, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('formula_list'))

@app.route('/export/lowest-cost')
def export_lowest_cost():
    """导出最低成本配方"""
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    filename = f"最低成本配方_{target_date}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_lowest_cost_to_excel(target_date, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('lowest_cost_today'))

@app.route('/export/materials-detail')
def export_materials_detail():
    """导出配方原料明细"""
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    search_keyword = request.args.get('search', '')
    formula_type = request.args.get('type', '')
    
    filename = f"配方原料明细_{target_date}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_materials_detail_to_excel(target_date, search_keyword, formula_type, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('materials_detail'))

@app.route('/export/materials-library')
def export_materials_library():
    """导出原料库"""
    search_keyword = request.args.get('search', '')
    
    filename = f"原料库_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_materials_library_to_excel(search_keyword, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('materials_library'))

@app.route('/export/material-price-history')
def export_material_price_history():
    """导出原料价格历史"""
    material_code = request.args.get('material_code', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    from export_data import export_material_price_history_to_excel
    
    filename = f"原料价格历史_{material_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_material_price_history_to_excel(material_code, start_date, end_date, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('material_detail', material_code=material_code))

@app.route('/export/customer-demands')
def export_customer_demands():
    """导出客户需求"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    filename = f"客户需求_{date}.xlsx"
    filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
    
    success, message = export_customer_demands_to_excel(date, filepath)
    
    if success:
        return send_file(filepath,
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        flash(message, 'danger')
        return redirect(url_for('customer_demands'))

# ========== 添加数据功能路由 ==========

@app.route('/add-formula')
def add_formula_page():
    """添加配方页面"""
    return render_template('add_formula.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/add-formula', methods=['POST'])
def add_formula():
    """处理添加配方"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 获取配方基本信息
        product_code = request.form.get('product_code')
        product_name = request.form.get('product_name')
        customer_product_name = request.form.get('customer_product_name')
        formula_type = request.form.get('formula_type')
        quotation_no = request.form.get('quotation_no')
        document_date = request.form.get('document_date')
        
        # 插入配方主表
        cursor.execute('''
            INSERT INTO formulas 
            (quotation_no, document_date, product_code, product_name, 
             customer_product_name, formula_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (quotation_no, document_date, product_code, product_name, 
              customer_product_name, formula_type))
        
        formula_id = cursor.lastrowid
        
        # 获取原料明细（从表单中获取动态添加的原料）
        material_codes = request.form.getlist('material_code[]')
        material_names = request.form.getlist('material_name[]')
        material_models = request.form.getlist('material_model[]')
        usage_ratios = request.form.getlist('usage_ratio[]')
        
        # 插入原料明细
        for i in range(len(material_codes)):
            if material_codes[i]:  # 只插入非空的原料
                cursor.execute('''
                    INSERT INTO formula_materials 
                    (formula_id, material_code, material_name, material_model, usage_ratio)
                    VALUES (?, ?, ?, ?, ?)
                ''', (formula_id, material_codes[i], material_names[i], 
                      material_models[i], float(usage_ratios[i])))
        
        conn.commit()
        conn.close()
        
        flash(f'配方添加成功！配方ID: {formula_id}', 'success')
        return redirect(url_for('formula_list'))
        
    except Exception as e:
        flash(f'配方添加失败: {str(e)}', 'danger')
        return redirect(url_for('add_formula_page'))

@app.route('/add-material')
def add_material_page():
    """添加原料页面"""
    return render_template('add_material.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/add-material', methods=['POST'])
def add_material():
    """处理添加原料价格"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        material_code = request.form.get('material_code')
        material_name = request.form.get('material_name')
        material_model = request.form.get('material_model')
        unit_price = float(request.form.get('unit_price'))
        price_date = request.form.get('price_date')
        
        # 插入原料价格
        cursor.execute('''
            INSERT OR REPLACE INTO daily_material_prices 
            (price_date, material_code, material_name, material_model, 
             unit_price, import_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (price_date, material_code, material_name, material_model, 
              unit_price, datetime.now().strftime('%Y-%m-%d')))
        
        conn.commit()
        conn.close()
        
        flash(f'原料价格添加成功！原料: {material_code} - {material_name}', 'success')
        return redirect(url_for('materials_library'))
        
    except Exception as e:
        flash(f'原料价格添加失败: {str(e)}', 'danger')
        return redirect(url_for('add_material_page'))

@app.route('/add-demand')
def add_demand_page():
    """添加客户需求页面"""
    return render_template('add_demand.html', current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/add-demand', methods=['POST'])
def add_demand():
    """处理添加客户需求（实际上是添加配方）"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 客户需求就是配方+产品信息
        customer_code = request.form.get('customer_code')
        customer_name = request.form.get('customer_name')
        product_code = request.form.get('product_code')
        product_name = request.form.get('product_name')
        customer_product_name = request.form.get('customer_product_name')
        formula_type = request.form.get('formula_type')
        quotation_no = request.form.get('quotation_no')
        document_date = request.form.get('document_date')
        
        # 先插入或更新产品信息
        cursor.execute('''
            INSERT OR IGNORE INTO products 
            (product_code, product_name, customer_code, customer_name)
            VALUES (?, ?, ?, ?)
        ''', (product_code, product_name, customer_code, customer_name))
        
        # 插入配方
        cursor.execute('''
            INSERT INTO formulas 
            (quotation_no, document_date, product_code, product_name, 
             customer_product_name, formula_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (quotation_no, document_date, product_code, product_name, 
              customer_product_name, formula_type))
        
        formula_id = cursor.lastrowid
        
        # 获取原料明细
        material_codes = request.form.getlist('material_code[]')
        material_names = request.form.getlist('material_name[]')
        material_models = request.form.getlist('material_model[]')
        usage_ratios = request.form.getlist('usage_ratio[]')
        
        # 插入原料明细
        for i in range(len(material_codes)):
            if material_codes[i]:
                cursor.execute('''
                    INSERT INTO formula_materials 
                    (formula_id, material_code, material_name, material_model, usage_ratio)
                    VALUES (?, ?, ?, ?, ?)
                ''', (formula_id, material_codes[i], material_names[i], 
                      material_models[i], float(usage_ratios[i])))
        
        conn.commit()
        conn.close()
        
        flash(f'客户需求添加成功！配方ID: {formula_id}', 'success')
        return redirect(url_for('customer_demands'))
        
    except Exception as e:
        flash(f'客户需求添加失败: {str(e)}', 'danger')
        return redirect(url_for('add_demand_page'))



# ==================== 配方编辑和删除 ====================

@app.route('/formulas/<int:formula_id>/edit', methods=['GET', 'POST'])
def edit_formula(formula_id):
    """编辑配方"""
    if request.method == 'GET':
        from data_manager import get_formula_by_id, get_all_products
        formula = get_formula_by_id(formula_id)
        
        if not formula:
            flash('配方不存在', 'danger')
            return redirect(url_for('formula_list'))
        
        # 获取所有产品用于下拉选择
        products = get_all_products()
        
        # 获取所有原料用于选择
        materials_list = get_all_materials()
        
        return render_template('edit_formula.html',
                             formula=formula,
                             products=products,
                             materials_list=materials_list,
                             current_date=datetime.now().strftime('%Y-%m-%d'))
    
    else:  # POST
        try:
            from data_manager import update_formula
            
            # 获取表单数据
            data = {
                'quotation_no': request.form.get('quotation_no'),
                'document_date': request.form.get('document_date'),
                'product_code': request.form['product_code'],
                'product_name': request.form.get('product_name'),
                'customer_product_name': request.form.get('customer_product_name'),
                'formula_type': request.form['formula_type']
            }
            
            # 获取原料数据
            material_codes = request.form.getlist('material_code[]')
            material_names = request.form.getlist('material_name[]')
            material_models = request.form.getlist('material_model[]')
            usage_ratios = request.form.getlist('usage_ratio[]')
            
            materials = []
            for i in range(len(material_codes)):
                if material_codes[i]:
                    materials.append({
                        'material_code': material_codes[i],
                        'material_name': material_names[i],
                        'material_model': material_models[i],
                        'usage_ratio': float(usage_ratios[i])
                    })
            
            data['materials'] = materials
            
            success, message = update_formula(formula_id, data)
            
            if success:
                flash(message, 'success')
                return redirect(url_for('formula_list'))
            else:
                flash(message, 'danger')
                return redirect(url_for('edit_formula', formula_id=formula_id))
        
        except Exception as e:
            flash(f'更新失败: {str(e)}', 'danger')
            return redirect(url_for('edit_formula', formula_id=formula_id))

@app.route('/formulas/<int:formula_id>/delete', methods=['POST'])
def delete_formula_route(formula_id):
    """删除配方"""
    try:
        from data_manager import delete_formula
        
        success, message = delete_formula(formula_id)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    
    except Exception as e:
        flash(f'删除失败: {str(e)}', 'danger')
    
    return redirect(url_for('formula_list'))

# ==================== 原料价格编辑和删除 ====================

@app.route('/materials/price/edit', methods=['POST'])
def edit_material_price():
    """编辑原料价格"""
    try:
        from data_manager import update_material_price
        
        price_date = request.form['price_date']
        material_code = request.form['material_code']
        new_price = float(request.form['unit_price'])
        
        success, message = update_material_price(price_date, material_code, new_price)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    
    except Exception as e:
        flash(f'更新失败: {str(e)}', 'danger')
    
    return redirect(url_for('material_detail', material_code=material_code))

@app.route('/materials/price/delete', methods=['POST'])
def delete_material_price_route():
    """删除原料价格"""
    try:
        from data_manager import delete_material_price
        
        price_date = request.form['price_date']
        material_code = request.form['material_code']
        
        success, message = delete_material_price(price_date, material_code)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    
    except Exception as e:
        flash(f'删除失败: {str(e)}', 'danger')
    
    return redirect(url_for('material_detail', material_code=material_code))


# ==================== 配方优化功能 ====================

@app.route('/substitution-rules')
def substitution_rules():
    """原料替换规则管理页面"""
    groups = get_all_material_groups()
    substitutions = get_all_substitutions()
    all_materials = get_all_materials_for_selection()
    
    return render_template('substitution_rules.html',
                         groups=groups,
                         substitutions=substitutions,
                         all_materials=all_materials)


@app.route('/substitution-rules/add-group', methods=['POST'])
def add_material_group():
    """添加原料分组"""
    group_name = request.form.get('group_name', '').strip()
    description = request.form.get('description', '').strip()
    
    if not group_name:
        flash('分组名称不能为空', 'danger')
        return redirect(url_for('substitution_rules'))
    
    success, group_id, message = create_material_group(group_name, description)
    
    if success:
        flash(message, 'success')
        return redirect(url_for('manage_group', group_id=group_id))
    else:
        flash(message, 'danger')
        return redirect(url_for('substitution_rules'))


@app.route('/substitution-rules/delete-group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    """删除原料分组"""
    success, message = delete_material_group(group_id)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('substitution_rules'))


@app.route('/substitution-rules/group/<int:group_id>')
def manage_group(group_id):
    """管理分组成员页面"""
    group = get_group_with_members(group_id)
    
    if not group:
        flash('分组不存在', 'danger')
        return redirect(url_for('substitution_rules'))
    
    all_materials = get_all_materials_for_selection()
    
    return render_template('manage_group.html',
                         group=group,
                         all_materials=all_materials)


@app.route('/substitution-rules/add-member', methods=['POST'])
def add_group_member():
    """添加原料到分组"""
    group_id = request.form.get('group_id', type=int)
    material_code = request.form.get('material_code', '').strip()
    conversion_factor = request.form.get('conversion_factor', 1.0, type=float)
    priority = request.form.get('priority', 0, type=int)
    
    if not group_id or not material_code:
        flash('参数不完整', 'danger')
        return redirect(url_for('substitution_rules'))
    
    success, message = add_member_to_group(group_id, material_code, '', conversion_factor, priority)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('manage_group', group_id=group_id))


@app.route('/substitution-rules/remove-member/<int:member_id>', methods=['POST'])
def remove_group_member(member_id):
    """从分组移除原料"""
    group_id = request.form.get('group_id', type=int)
    
    success, message = remove_member_from_group(member_id)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    if group_id:
        return redirect(url_for('manage_group', group_id=group_id))
    return redirect(url_for('substitution_rules'))


@app.route('/substitution-rules/add-substitution', methods=['POST'])
def add_substitution_rule():
    """添加直接替换规则"""
    source_code = request.form.get('source_code', '').strip()
    target_code = request.form.get('target_code', '').strip()
    conversion_factor = request.form.get('conversion_factor', 1.0, type=float)
    max_ratio = request.form.get('max_ratio', 1.0, type=float)
    notes = request.form.get('notes', '').strip()
    
    if not source_code or not target_code:
        flash('请选择源原料和替代原料', 'danger')
        return redirect(url_for('substitution_rules'))
    
    if source_code == target_code:
        flash('源原料和替代原料不能相同', 'danger')
        return redirect(url_for('substitution_rules'))
    
    success, message = add_substitution(source_code, target_code, conversion_factor, max_ratio, notes)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('substitution_rules'))


@app.route('/substitution-rules/delete-substitution/<int:sub_id>', methods=['POST'])
def delete_substitution_rule(sub_id):
    """删除替换规则"""
    success, message = delete_substitution(sub_id)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    
    return redirect(url_for('substitution_rules'))


@app.route('/optimize-formula')
def optimize_formula_page():
    """配方优化页面"""
    search_keyword = request.args.get('search', '')
    target_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    formula_id = request.args.get('formula_id', type=int)
    
    # 获取报价配方列表
    quotation_formulas = get_quotation_formulas_for_optimization()
    
    # 如果有搜索关键词，过滤配方
    if search_keyword:
        quotation_formulas = [f for f in quotation_formulas 
                            if search_keyword.lower() in f['product_code'].lower() 
                            or search_keyword.lower() in f['product_name'].lower()]
    
    # 如果选择了配方，执行优化
    selected_formula = None
    if formula_id:
        result, message = optimize_formula(formula_id, target_date)
        if result:
            selected_formula = result
        else:
            flash(message, 'danger')
    
    # 获取统计信息
    groups = get_all_material_groups()
    substitutions = get_all_substitutions()
    stats = {
        'group_count': len(groups),
        'substitution_count': len(substitutions)
    }
    
    # 获取优化历史
    optimization_history = get_optimized_formula_history()
    
    return render_template('optimize_formula.html',
                         quotation_formulas=quotation_formulas,
                         selected_formula=selected_formula,
                         search_keyword=search_keyword,
                         target_date=target_date,
                         stats=stats,
                         optimization_history=optimization_history)


@app.route('/optimize-formula/apply', methods=['POST'])
def apply_optimization():
    """应用优化结果生成生产配方"""
    formula_id = request.form.get('formula_id', type=int)
    target_date = request.form.get('target_date', datetime.now().strftime('%Y-%m-%d'))
    
    if not formula_id:
        flash('参数错误', 'danger')
        return redirect(url_for('optimize_formula_page'))
    
    # 先执行优化
    result, message = optimize_formula(formula_id, target_date)
    
    if not result:
        flash(f'优化失败: {message}', 'danger')
        return redirect(url_for('optimize_formula_page'))
    
    # 保存优化结果
    success, opt_id, save_message = save_optimized_formula(result)
    
    if not success:
        flash(f'保存失败: {save_message}', 'danger')
        return redirect(url_for('optimize_formula_page'))
    
    # 应用优化结果创建生产配方
    success, apply_message = apply_optimized_formula(opt_id)
    
    if success:
        flash(f'生产配方生成成功！{apply_message}', 'success')
    else:
        flash(f'生成失败: {apply_message}', 'danger')
    
    return redirect(url_for('formula_list'))


# ==================== AI助手功能 ====================

@app.route('/ai-assistant')
def ai_assistant():
    """AI配方助手页面"""
    # 获取API配置状态
    config = get_api_config()
    api_configured = bool(config['api_key'])
    
    # 获取统计信息
    materials = get_all_materials_for_selection()
    formulas = get_quotation_formulas_for_optimization()
    groups = get_all_material_groups()
    substitutions = get_all_substitutions()
    
    stats = {
        'materials_count': len(materials),
        'formula_count': len(formulas),
        'rules_count': len(substitutions),
        'groups_count': len(groups)
    }
    
    # 获取session中的对话历史和AI结果
    chat_history = session.get('chat_history', [])
    ai_result = session.get('ai_result', None)
    
    return render_template('ai_assistant.html',
                         api_configured=api_configured,
                         current_provider=LLM_CONFIG['provider'],
                         current_api_key=config['api_key'][:10] + '***' if config['api_key'] else '',
                         stats=stats,
                         formulas=formulas[:100],  # 限制数量
                         chat_history=chat_history[-10:],  # 只显示最近10条
                         ai_result=ai_result)


@app.route('/ai-assistant/settings', methods=['POST'])
def save_api_settings():
    """保存API设置"""
    provider = request.form.get('provider', 'siliconflow')
    api_key = request.form.get('api_key', '').strip()
    
    set_provider(provider)
    if api_key:
        set_api_key(api_key, provider)
        flash(f'API设置已保存！当前使用: {provider}', 'success')
    else:
        flash('请填入API Key', 'warning')
    
    return redirect(url_for('ai_assistant'))


@app.route('/ai-assistant/suggest-rules', methods=['POST'])
def ai_suggest_rules():
    """AI分析原料库，建议替换规则"""
    materials = get_all_materials_for_selection()
    
    success, summary, result = ai_suggest_substitutions(materials)
    
    if success:
        session['ai_result'] = {
            'type': 'suggestions',
            'summary': summary,
            'data': result
        }
        flash('AI分析完成！请查看下方建议。', 'success')
    else:
        flash(f'AI分析失败: {summary}', 'danger')
        session['ai_result'] = None
    
    return redirect(url_for('ai_assistant'))


@app.route('/ai-assistant/optimize', methods=['POST'])
def ai_optimize():
    """AI优化配方"""
    formula_id = request.form.get('formula_id', type=int)
    requirements = request.form.get('requirements', '')
    
    if not formula_id:
        flash('请选择配方', 'warning')
        return redirect(url_for('ai_assistant'))
    
    # 获取配方信息
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, product_code, product_name, customer_product_name, formula_type
        FROM formulas WHERE id = ?
    ''', (formula_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        flash('配方不存在', 'danger')
        return redirect(url_for('ai_assistant'))
    
    formula_info = {
        'id': row[0],
        'product_code': row[1],
        'product_name': row[2],
        'customer_product_name': row[3],
        'formula_type': row[4]
    }
    
    # 获取配方原料
    materials = get_formula_materials_with_prices(formula_id, datetime.now().strftime('%Y-%m-%d'))
    
    # 获取所有可用原料
    all_materials = get_all_materials_for_selection()
    
    # 调用AI优化
    success, notes, result = ai_optimize_formula(formula_info, materials, all_materials, requirements)
    
    if success:
        session['ai_result'] = {
            'type': 'optimization',
            'notes': notes,
            'data': result
        }
        flash('AI优化分析完成！', 'success')
    else:
        flash(f'AI优化失败: {notes}', 'danger')
        session['ai_result'] = None
    
    return redirect(url_for('ai_assistant'))


@app.route('/ai-assistant/chat', methods=['POST'])
def ai_chat():
    """AI对话"""
    message = request.form.get('message', '').strip()
    
    if not message:
        return redirect(url_for('ai_assistant'))
    
    # 获取对话历史
    chat_history = session.get('chat_history', [])
    
    # 添加用户消息
    chat_history.append({'role': 'user', 'content': message})
    
    # 准备上下文
    materials = get_all_materials_for_selection()
    context = {
        'materials_count': len(materials),
        'formula_count': len(get_quotation_formulas_for_optimization()),
        'recent_materials': [m['material_name'] for m in materials[:20]]
    }
    
    # 调用AI
    success, response = ai_chat_assistant(message, context)
    
    if success:
        chat_history.append({'role': 'assistant', 'content': response})
    else:
        chat_history.append({'role': 'assistant', 'content': f'抱歉，出错了: {response}'})
    
    # 保存对话历史（只保留最近20条）
    session['chat_history'] = chat_history[-20:]
    
    return redirect(url_for('ai_assistant'))


@app.route('/ai-assistant/apply-suggestion', methods=['POST'])
def apply_ai_suggestion():
    """采纳AI建议的替换规则"""
    source_code = request.form.get('source_code', '')
    target_code = request.form.get('target_code', '')
    conversion_factor = request.form.get('conversion_factor', 1.0, type=float)
    
    if not source_code or not target_code:
        flash('参数错误', 'danger')
        return redirect(url_for('ai_assistant'))
    
    success, message = add_substitution(source_code, target_code, conversion_factor, 1.0, 'AI建议')
    
    if success:
        flash(f'已采纳: {message}', 'success')
    else:
        flash(message, 'warning')
    
    return redirect(url_for('ai_assistant'))


@app.route('/ai-assistant/clear-history', methods=['POST'])
def clear_chat_history():
    """清空对话历史"""
    session.pop('chat_history', None)
    session.pop('ai_result', None)
    flash('对话历史已清空', 'info')
    return redirect(url_for('ai_assistant'))


if __name__ == '__main__':
    init_database()
    init_optimizer_tables()  # 初始化优化器表
    app.run(host='0.0.0.0', port=8080, debug=True)

