//go:build no_memcache

package reservation

import (
	"context"
	"time"

	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/reservation/proto"
)

// CheckAvailability checks if given information is available by querying MongoDB directly.
// No Memcached calls are made in this build variant.
func (s *Server) CheckAvailability(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := new(pb.Result)
	res.HotelId = make([]string, 0)

	numCollection := s.MongoClient.Database("reservation-db").Collection("number")
	resCollection := s.MongoClient.Database("reservation-db").Collection("reservation")

	for _, hotelId := range req.HotelId {
		log.Trace().Msgf("reservation check hotel %s", hotelId)

		// Query capacity from number collection
		var num number
		err := numCollection.FindOne(context.TODO(), bson.D{{"hotelId", hotelId}}).Decode(&num)
		if err != nil {
			log.Error().Msgf("Failed to get hotel capacity for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}
		hotelCap := num.Number

		inDate, _ := time.Parse(
			time.RFC3339,
			req.InDate+"T12:00:00+00:00")
		outDate, _ := time.Parse(
			time.RFC3339,
			req.OutDate+"T12:00:00+00:00")

		available := true
		for inDate.Before(outDate) {
			indate := inDate.String()[:10]
			inDate = inDate.AddDate(0, 0, 1)
			outdate := inDate.String()[:10]

			// Query reservation counts from reservation collection
			var reserve []reservation
			filter := bson.D{{"hotelId", hotelId}, {"inDate", indate}, {"outDate", outdate}}
			curr, err := resCollection.Find(context.TODO(), filter)
			if err != nil {
				log.Error().Msgf("Failed to get reservation data for hotelId [%v]: %v", hotelId, err)
				return nil, err
			}
			if err = curr.All(context.TODO(), &reserve); err != nil {
				log.Error().Msgf("Failed to decode reservation data for hotelId [%v]: %v", hotelId, err)
				return nil, err
			}

			count := 0
			for _, r := range reserve {
				count += r.Number
			}

			if count+int(req.RoomNumber) > hotelCap {
				available = false
				break
			}
		}

		if available {
			res.HotelId = append(res.HotelId, hotelId)
		}
	}

	return res, nil
}

// MakeReservation makes a reservation based on given information by querying MongoDB directly.
// No Memcached calls are made in this build variant.
func (s *Server) MakeReservation(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := new(pb.Result)
	res.HotelId = make([]string, 0)

	database := s.MongoClient.Database("reservation-db")
	resCollection := database.Collection("reservation")
	numCollection := database.Collection("number")

	inDate, _ := time.Parse(
		time.RFC3339,
		req.InDate+"T12:00:00+00:00")
	outDate, _ := time.Parse(
		time.RFC3339,
		req.OutDate+"T12:00:00+00:00")
	hotelId := req.HotelId[0]

	// Query capacity from number collection
	var num number
	err := numCollection.FindOne(context.TODO(), bson.D{{"hotelId", hotelId}}).Decode(&num)
	if err != nil {
		log.Error().Msgf("Failed to get hotel capacity for hotelId [%v]: %v", hotelId, err)
		return nil, err
	}
	hotelCap := num.Number

	indate := inDate.String()[0:10]

	// Check availability for each day in the date range
	for cur := inDate; cur.Before(outDate); {
		nextDate := cur.AddDate(0, 0, 1)
		outdate := nextDate.String()[0:10]

		// Query reservation counts from reservation collection
		var reserve []reservation
		filter := bson.D{{"hotelId", hotelId}, {"inDate", indate}, {"outDate", outdate}}
		curr, err := resCollection.Find(context.TODO(), filter)
		if err != nil {
			log.Error().Msgf("Failed to get reservation data for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}
		if err = curr.All(context.TODO(), &reserve); err != nil {
			log.Error().Msgf("Failed to decode reservation data for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}

		count := 0
		for _, r := range reserve {
			count += r.Number
		}

		if count+int(req.RoomNumber) > hotelCap {
			// Not enough capacity — return empty result (no hotel ID added)
			return res, nil
		}

		indate = outdate
		cur = nextDate
	}

	// Capacity check passed — insert reservation records for each day
	inDate, _ = time.Parse(
		time.RFC3339,
		req.InDate+"T12:00:00+00:00")
	indate = inDate.String()[0:10]

	for inDate.Before(outDate) {
		inDate = inDate.AddDate(0, 0, 1)
		outdate := inDate.String()[0:10]
		_, err := resCollection.InsertOne(
			context.TODO(),
			reservation{
				HotelId:      hotelId,
				CustomerName: req.CustomerName,
				InDate:       indate,
				OutDate:      outdate,
				Number:       int(req.RoomNumber),
			},
		)
		if err != nil {
			log.Error().Msgf("Failed to insert reservation for hotelId [%v]: %v", hotelId, err)
			return nil, err
		}
		indate = outdate
	}

	res.HotelId = append(res.HotelId, hotelId)

	return res, nil
}
