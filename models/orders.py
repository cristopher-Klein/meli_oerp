# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import fields, osv, models, api
import logging
from .meli_oerp_config import *

from ..melisdk.meli import Meli

import json

import logging
_logger = logging.getLogger(__name__)

from . import posting
from . import product
from . import shipment
#https://api.mercadolibre.com/questions/search?item_id=MLA508223205

from dateutil.parser import *
from datetime import *

class sale_order_line(models.Model):
    _inherit = "sale.order.line"

    meli_order_item_id = fields.Char('Meli Order Item Id');
sale_order_line()

class sale_order(models.Model):
    _inherit = "sale.order"

    meli_order_id =  fields.Char('Meli Order Id');
    meli_status = fields.Selection( [
        #Initial state of an order, and it has no payment yet.
                                        ("confirmed","Confirmado"),
        #The order needs a payment to become confirmed and show users information.
                                      ("payment_required","Pago requerido"),
        #There is a payment related with the order, but it has not accredited yet
                                    ("payment_in_process","Pago en proceso"),
        #The order has a related payment and it has been accredited.
                                    ("paid","Pagado"),
        #The order has not completed by some reason.
                                    ("cancelled","Cancelado")], string='Order Status');

    meli_status_detail = fields.Text(string='Status detail, in case the order was cancelled.');
    meli_date_created = fields.Date('Creation date');
    meli_date_closed = fields.Date('Closing date');

#        'meli_order_items': fields.one2many('mercadolibre.order_items','order_id','Order Items' ),
#        'meli_payments': fields.one2many('mercadolibre.payments','order_id','Payments' ),
    meli_shipping = fields.Text(string="Shipping");

    meli_total_amount = fields.Char(string='Total amount');
    meli_currency_id = fields.Char(string='Currency');
#        'buyer': fields.many2one( "mercadolibre.buyers","Buyer"),
#       'meli_seller': fields.text( string='Seller' ),


sale_order()

class res_partner(models.Model):
    _inherit = "res.partner"


    meli_buyer_id = fields.Char('Meli Buyer Id')
    meli_buyer = fields.Many2one( "mercadolibre.buyers","Buyer")


res_partner()

class mercadolibre_orders(models.Model):
    _name = "mercadolibre.orders"
    _description = "Pedidos en MercadoLibre"

    def street(self, Receiver ):
        full_street = 'no street'
        if (Receiver and 'address_line' in Receiver):
            full_street = Receiver['address_line']

        return full_street

    def city(self, Receiver ):
        full_city = ''
        if (Receiver and 'city' in Receiver):
            full_city = Receiver['city']['name']

        return full_city

    def state(self, country_id, Receiver ):
        full_state = ''
        state_id = False
        if (Receiver and 'state' in Receiver):
            full_state = Receiver['state']['name']
            state = self.env['res.country.state'].search(['&',('name','like',full_state),('country_id','=',country_id)])
            if (len(state)==1):
                state_id = state.id
            else:
                if (len(state)>1):
                    state_id = state[0].id


        return state_id

    def country(self, Receiver ):
        full_country = ''
        country_id = False
        if (Receiver and 'country' in Receiver):
            full_country = Receiver['country']['name']
            country = self.env['res.country'].search([('name','like',full_country)])
            if (len(country)):
                country_id = country.id


        return country_id

    def billing_info( self, billing_json, context=None ):
        billinginfo = ''

        if 'doc_type' in billing_json:
            if billing_json['doc_type']:
                billinginfo+= billing_json['doc_type']

        if 'doc_number' in billing_json:
            if billing_json['doc_number']:
                billinginfo+= billing_json['doc_number']

        return billinginfo

    def full_phone( self, phone_json, context=None ):
        full_phone = ''

        if 'area_code' in phone_json:
            if phone_json['area_code']:
                full_phone+= phone_json['area_code']

        if 'number' in phone_json:
            if phone_json['number']:
                full_phone+= phone_json['number']

        if 'extension' in phone_json:
            if phone_json['extension']:
                full_phone+= phone_json['extension']

        return full_phone

    def pretty_json( self, ids, data, indent=0, context=None ):
        return json.dumps( data, sort_keys=False, indent=4 )

    def orders_update_order_json( self, data, context=None ):

        _logger.info("orders_update_order_json > data "+str(data['id']) )
        oid = data["id"]
        order_json = data["order_json"]
        #_logger.info( "data:" + str(data) )
        #_logger.info("orders_update_order_json > data[id]: " + oid + " order_json:" + order_json )
        company = self.env.user.company_id

        saleorder_obj = self.env['sale.order']
        saleorderline_obj = self.env['sale.order.line']
        product_obj = self.env['product.product']

        pricelist_obj = self.env['product.pricelist']
        respartner_obj = self.env['res.partner']

        plistid = None
        if company.mercadolibre_pricelist:
            plistid = company.mercadolibre_pricelist
        else:
            plistids = pricelist_obj.search([])[0]
            if plistids:
                plistid = plistids


        order_obj = self.env['mercadolibre.orders']
        buyers_obj = self.env['mercadolibre.buyers']
        posting_obj = self.env['mercadolibre.posting']
        order_items_obj = self.env['mercadolibre.order_items']
        payments_obj = self.env['mercadolibre.payments']
        shipment_obj = self.env['mercadolibre.shipment']


        order = None
        sorder = None

        # if id is defined, we are updating existing one
        if (oid):
            order = order_obj.browse(oid )
            ##sorder = order_obj.browse(
            sorder = saleorder_obj.browse(oid )
        else:
        #we search for existing order with same order_id => "id"
            order_s = order_obj.search([ ('order_id','=',order_json['id']) ] )
            if (order_s):
                order = order_s
            #    order = order_obj.browse(order_s[0] )

            sorder_s = saleorder_obj.search([ ('meli_order_id','=',order_json['id']) ] )
            if (sorder_s):
                sorder = sorder_s
            #if (sorder_s and len(sorder_s)>0):
            #    sorder = saleorder_obj.browse(sorder_s[0] )

        order_fields = {
            'order_id': '%i' % (order_json["id"]),
            'status': order_json["status"],
            'status_detail': order_json["status_detail"] or '' ,
            'total_amount': order_json["total_amount"],
            'currency_id': order_json["currency_id"],
            'date_created': order_json["date_created"] or '',
            'date_closed': order_json["date_closed"] or '',
        }

        #_logger.info( "order:" + str(order) )

        if 'buyer' in order_json:
            Buyer = order_json['buyer']
            Receiver = False
            if ('shipping' in order_json):
                if ('receiver_address' in order_json['shipping']):
                    Receiver = order_json['shipping']['receiver_address']
            meli_buyer_fields = {
                'name': Buyer['first_name']+' '+Buyer['last_name'],
                'street': self.street(Receiver),
                'city': self.city(Receiver),
                'country_id': self.country(Receiver),
                'state_id': self.state(self.country(Receiver),Receiver),
                'phone': self.full_phone( Buyer['phone']),
                'email': Buyer['email'],
                'meli_buyer_id': Buyer['id']
            }

            buyer_fields = {
                'buyer_id': Buyer['id'],
                'nickname': Buyer['nickname'],
                'email': Buyer['email'],
                'phone': self.full_phone( Buyer['phone']),
                'alternative_phone': self.full_phone( Buyer['alternative_phone']),
                'first_name': Buyer['first_name'],
                'last_name': Buyer['last_name'],
                'billing_info': self.billing_info(Buyer['billing_info']),
            }

            buyer_ids = buyers_obj.search([  ('buyer_id','=',buyer_fields['buyer_id'] ) ] )
            buyer_id = 0
            if (buyer_ids==False or len(buyer_ids)==0):
                _logger.info( "creating buyer")
                _logger.info(buyer_fields)
                buyer_id = buyers_obj.create(( buyer_fields ))
            else:
                buyer_id = buyer_ids
                buyer_id.write( ( buyer_fields ) )
                #if (len(buyer_ids)>0):
                #      buyer_id = buyer_ids[0]
            if (buyer_id):
                meli_buyer_fields['meli_buyer'] = buyer_id.id

            partner_ids = respartner_obj.search([  ('meli_buyer_id','=',buyer_fields['buyer_id'] ) ] )
            partner_id = 0
            if not partner_ids:
                #_logger.info( "creating partner:" + str(meli_buyer_fields) )
                partner_id = respartner_obj.create(( meli_buyer_fields ))
            else:
                partner_id = partner_ids
                _logger.info("Updating partner")
                partner_id.write(meli_buyer_fields)

            if order and buyer_id:
                return_id = order.write({'buyer':buyer_id.id})

        if (len(partner_ids)>0):
            partner_id = partner_ids[0]
        #process base order fields
        meli_order_fields = {
            'partner_id': partner_id.id,
            'pricelist_id': plistid.id,
            'meli_order_id': '%i' % (order_json["id"]),
            'meli_status': order_json["status"],
            'meli_status_detail': order_json["status_detail"] or '' ,
            'meli_total_amount': order_json["total_amount"],
            'meli_currency_id': order_json["currency_id"],
            'meli_date_created': order_json["date_created"] or '',
            'meli_date_closed': order_json["date_closed"] or '',
        }

        if (order_json["shipping"]):
            order_fields['shipping'] = self.pretty_json( id, order_json["shipping"] )
            meli_order_fields['meli_shipping'] = self.pretty_json( id, order_json["shipping"] )
            if ("id" in order_json["shipping"]):
                order_fields['shipping_id'] = order_json["shipping"]["id"]


        #create or update order
        if (order and order.id):
            _logger.info("Updating order: %s" % (order.id))
            order.write( order_fields )
        else:
            _logger.info("Adding new order: " )
            _logger.info(order_fields)
            #_logger.info( "creating order:" + str(order_fields) )
            order = order_obj.create( (order_fields))

        if (sorder and sorder.id):
            _logger.info("Updating sale.order: %s" % (sorder.id))
            sorder.write( meli_order_fields )
        else:
            _logger.info("Adding new sale.order: " )
            _logger.info(meli_order_fields)
            #_logger.info( "creating sale order:" + str(meli_order_fields) )
            sorder = saleorder_obj.create((meli_order_fields))

        #check error
        if not order:
            _logger.error("Error adding order. " )
            return {'error': 'Error adding order' }

        #check error
        if not sorder:
            _logger.error("Error adding sale.order. " )
            return {'error': 'Error adding sale.order' }

        #update internal fields (items, payments, buyers)
        if 'order_items' in order_json:
            items = order_json['order_items']
            #_logger.info( items )
            cn = 0
            for Item in items:
                cn = cn + 1
                #_logger.info(cn)
                #_logger.info(Item )
                post_related_obj = ''
                product_related_obj = ''
                product_related_obj_id = False

                post_related = posting_obj.search([('meli_id','=',Item['item']['id'])])
                if (post_related):
                    _logger.info("order post related by meli_id:",post_related)
                else:
                    #create post!
                    posting_fields = {
                        'posting_date': str(datetime.now()),
                        'meli_id':Item['item']['id'],
                        'name': 'Order: ' + Item['item']['title'] }

                    post_related = self.env['mercadolibre.posting'].create((posting_fields))

                if len(post_related):
                    post_related_obj = post_related
                    #_logger.info( post_related_obj )
                    #if (post_related[0]):
                    #    post_related_obj = post_related[0]
                else:
                    _logger.info( "No post related, exiting" )
                    return { 'error': 'No post related, exiting'}

                #_logger.info( "Search product related." )
                product_related = product_obj.search([('meli_id','=',Item['item']['id'])])
                if (product_related):
                    _logger.info("order product related by meli_id:",product_related)
                else:
                    if ('seller_custom_field' in Item['item']):
                        product_related = product_obj.search([('default_code','=',Item['item']['seller_custom_field'])])
                        if (product_related):
                            _logger.info("order product related by seller_custom_field and default_code:",product_related)

                if len(product_related):
                    if len(product_related)>1:
                        last_p = False
                        for p in product_related:
                            last_p = p
                            if (p.product_tmpl_id.meli_pub_principal_variant):
                                product_related_obj = p.product_tmpl_id.meli_pub_principal_variant
                            if (p.meli_default_stock_product):
                                product_related_obj = p.meli_default_stock_product

                        if (product_related_obj):
                            product_related_obj = product_related_obj
                        else:
                            product_related_obj = last_p
                    else:
                        product_related_obj = product_related

                if (post_related and product_related):
                    if (post_related.product_id==False):
                        post_related.product_id = product_related

                order_item_fields = {
                    'order_id': order.id,
                    'posting_id': post_related_obj.id,
                    'order_item_id': Item['item']['id'],
                    'order_item_title': Item['item']['title'],
                    'order_item_category_id': Item['item']['category_id'],
                    'unit_price': Item['unit_price'],
                    'quantity': Item['quantity'],
                    'currency_id': Item['currency_id']
                }
                order_item_ids = order_items_obj.search( [('order_item_id','=',order_item_fields['order_item_id']),('order_id','=',order.id)] )
                #_logger.info( order_item_fields )
                if not order_item_ids:
                    #_logger.info( "order_item_fields: " + str(order_item_fields) )
                    order_item_ids = order_items_obj.create( ( order_item_fields ))
                else:
                    order_item_ids.write( ( order_item_fields ) )

                if (product_related_obj == False or len(product_related_obj)==0):
                    _logger.error("No product related to meli_id:"+str(Item['item']['id']))
                    return { 'error': 'No product related to meli_id' }

                saleorderline_item_fields = {
                    'company_id': company.id,
                    'order_id': sorder.id,
                    'meli_order_item_id': Item['item']['id'],
                    #'price_unit': float(Item['unit_price']),
                    ####'price_total': float(Item['unit_price']) * float(Item['quantity']),
                    #'tax_id': None,
                    'product_id': product_related_obj.id,
                    'product_uom_qty': Item['quantity'],
                    'product_uom': 1,
                    'name': Item['item']['title'],
                    #'customer_lead': float(0)
                }
                if (float(Item['unit_price'])==product_related_obj.product_tmpl_id.lst_price):
                    saleorderline_item_fields['price_unit'] = float(Item['unit_price'])
                    saleorderline_item_fields['tax_id'] = None
                else:
                    saleorderline_item_fields['price_unit'] = product_related_obj.product_tmpl_id.lst_price

                saleorderline_item_ids = saleorderline_obj.search( [('meli_order_item_id','=',saleorderline_item_fields['meli_order_item_id']),('order_id','=',sorder.id)] )
                #_logger.info( saleorderline_item_fields )

                if not saleorderline_item_ids:
                    #_logger.info( "saleorderline_item_fields: " + str(saleorderline_item_fields) )
                    saleorderline_item_ids = saleorderline_obj.create( ( saleorderline_item_fields ))
                else:
                    saleorderline_item_ids.write( ( saleorderline_item_fields ) )


        if 'payments' in order_json:
            payments = order_json['payments']
            #_logger.info( payments )
            cn = 0
            for Payment in payments:
                cn = cn + 1
                #_logger.info(cn)
                #_logger.info(Payment )

                payment_fields = {
                    'order_id': order.id,
                    'payment_id': Payment['id'],
                    'transaction_amount': Payment['transaction_amount'] or '',
                    'currency_id': Payment['currency_id'] or '',
                    'status': Payment['status'] or '',
                    'date_created': Payment['date_created'] or '',
                    'date_last_modified': Payment['date_last_modified'] or '',
                }

                payment_ids = payments_obj.search( [  ('payment_id','=',payment_fields['payment_id']),
                                                            ('order_id','=',order.id ) ] )

                if not payment_ids:
	                payment_ids = payments_obj.create( ( payment_fields ))
                else:
                    payment_ids.write( ( payment_fields ) )


        if order:
            return_id = self.env['mercadolibre.orders'].update


        if company.mercadolibre_cron_get_orders_shipment:
            _logger.info("Updating order: Shipment")
            if (order.shipping_id):
                shipment_obj.fetch( order )


        return {}

    def orders_update_order( self, context=None ):

        #get with an item id
        company = self.env.user.company_id

        order_obj = self.env['mercadolibre.orders']
        order = self

        log_msg = 'orders_update_order: %s' % (order.order_id)
        _logger.info(log_msg)

        CLIENT_ID = company.mercadolibre_client_id
        CLIENT_SECRET = company.mercadolibre_secret_key
        ACCESS_TOKEN = company.mercadolibre_access_token
        REFRESH_TOKEN = company.mercadolibre_refresh_token

        #
        meli = Meli(client_id=CLIENT_ID,client_secret=CLIENT_SECRET, access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN )

        response = meli.get("/orders/"+order.order_id, {'access_token':meli.access_token})
        order_json = response.json()
        #_logger.info( order_json )

        if "error" in order_json:
            _logger.error( order_json["error"] )
            _logger.error( order_json["message"] )
        else:
            try:
                self.orders_update_order_json( {"id": order.id, "order_json": order_json } )
                self._cr.commit()
            except Exception as e:
                _logger.info("orders_update_order > Error actualizando ORDEN")
                _logger.error(e, exc_info=True)
                pass

        return {}


    def orders_query_iterate( self, offset=0, context=None ):


        offset_next = 0

        company = self.env.user.company_id

        orders_obj = self.env['mercadolibre.orders']

        CLIENT_ID = company.mercadolibre_client_id
        CLIENT_SECRET = company.mercadolibre_secret_key
        ACCESS_TOKEN = company.mercadolibre_access_token
        REFRESH_TOKEN = company.mercadolibre_refresh_token

        #
        meli = Meli(client_id=CLIENT_ID,client_secret=CLIENT_SECRET, access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN )

        orders_query = "/orders/search?seller="+company.mercadolibre_seller_id+"&sort=date_desc"

        if (offset):
            orders_query = orders_query + "&offset="+str(offset).strip()

        response = meli.get( orders_query, {'access_token':meli.access_token})
        orders_json = response.json()

        if "error" in orders_json:
            _logger.error( orders_query )
            _logger.error( orders_json["error"] )
            if (orders_json["message"]=="invalid_token"):
                _logger.error( orders_json["message"] )
            return {}


        if "paging" in orders_json:
            if "total" in orders_json["paging"]:
                if (orders_json["paging"]["total"]==0):
                    return {}
                else:
                    if (orders_json["paging"]["total"]==orders_json["paging"]["limit"]):
                        offset_next = offset + orders_json["paging"]["limit"]

        if "results" in orders_json:
            for order_json in orders_json["results"]:
                if order_json:
                    #_logger.info( order_json )
                    pdata = {"id": False, "order_json": order_json}
                    try:
                        self.orders_update_order_json( pdata )
                        self._cr.commit()
                    except Exception as e:
                        _logger.info("orders_query_iterate > Error actualizando ORDEN")
                        _logger.error(e, exc_info=True)
                        pass


        if (offset_next>0):
            self.orders_query_iterate(offset_next)

        return {}

    def orders_query_recent( self ):

        self._cr.autocommit(False)

        try:
            self.orders_query_iterate( 0 )
        except Exception as e:
            _logger.info("orders_query_recent > Error iterando ordenes")
            _logger.error(e, exc_info=True)
            self._cr.rollback()

        return {}

    order_id = fields.Char('Order Id');

    status = fields.Selection( [
        #Initial state of an order, and it has no payment yet.
                                        ("confirmed","Confirmado"),
        #The order needs a payment to become confirmed and show users information.
                                      ("payment_required","Pago requerido"),
        #There is a payment related with the order, but it has not accredited yet
                                    ("payment_in_process","Pago en proceso"),
        #The order has a related payment and it has been accredited.
                                    ("paid","Pagado"),
        #The order has not completed by some reason.
                                    ("cancelled","Cancelado")], string='Order Status');

    status_detail = fields.Text(string='Status detail, in case the order was cancelled.');
    date_created = fields.Date('Creation date');
    date_closed = fields.Date('Closing date');

    order_items = fields.One2many('mercadolibre.order_items','order_id','Order Items' );
    payments = fields.One2many('mercadolibre.payments','order_id','Payments' );
    shipping = fields.Text(string="Shipping");
    shipping_id = fields.Char(string="Shipping id");
    shipment = fields.One2many('mercadolibre.shipment','shipping_id','Shipment')


    total_amount = fields.Char(string='Total amount');
    currency_id = fields.Char(string='Currency');
    buyer =  fields.Many2one( "mercadolibre.buyers","Buyer");
    seller = fields.Text( string='Seller' );


mercadolibre_orders()


class mercadolibre_order_items(models.Model):
    _name = "mercadolibre.order_items"
    _description = "Producto pedido en MercadoLibre"

    posting_id = fields.Many2one("mercadolibre.posting","Posting");
    order_id = fields.Many2one("mercadolibre.orders","Order");
    order_item_id = fields.Char('Item Id');
    order_item_title = fields.Char('Item Title');
    order_item_category_id = fields.Char('Item Category Id');
    unit_price = fields.Char(string='Unit price');
    quantity = fields.Integer(string='Quantity');
    #       'total_price': fields.char(string='Total price'),
    currency_id = fields.Char(string='Currency');

mercadolibre_order_items()


class mercadolibre_payments(models.Model):
	_name = "mercadolibre.payments"
	_description = "Pagos en MercadoLibre"

	order_id = fields.Many2one("mercadolibre.orders","Order");
	payment_id = fields.Char('Payment Id',index=True);
	transaction_amount = fields.Char('Transaction Amount');
	currency_id = fields.Char(string='Currency');
	status = fields.Char(string='Payment Status');
	date_created = fields.Date('Creation date');
	date_last_modified = fields.Date('Modification date');

mercadolibre_payments()

class mercadolibre_buyers(models.Model):
    _name = "mercadolibre.buyers"
    _description = "Compradores en MercadoLibre"

    buyer_id = fields.Char(string='Buyer ID',index=True);
    nickname = fields.Char(string='Nickname');
    email = fields.Char(string='Email');
    phone = fields.Char( string='Phone');
    alternative_phone = fields.Char( string='Alternative Phone');
    first_name = fields.Char( string='First Name');
    last_name = fields.Char( string='Last Name');
    billing_info = fields.Char( string='Billing Info');

mercadolibre_buyers()


class mercadolibre_orders_update(models.TransientModel):
    _name = "mercadolibre.orders.update"
    _description = "Update Order"

    def order_update(self, context):

        orders_ids = context['active_ids']
        orders_obj = self.env['mercadolibre.orders']

        self._cr.autocommit(False)
        try:

            for order_id in orders_ids:

                _logger.info("order_update: %s " % (order_id) )

                order = orders_obj.browse(order_id)
                order.orders_update_order()

        except Exception as e:
            _logger.info("order_update > Error actualizando ordenes")
            _logger.error(e, exc_info=True)
            self._cr.rollback()

        return {}

mercadolibre_orders_update()
